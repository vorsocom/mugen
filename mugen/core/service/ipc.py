"""Provides an implementation of IIPCService."""

__all__ = ["DefaultIPCService"]

import asyncio
from time import perf_counter
from types import SimpleNamespace
from typing import Any

from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import (
    IIPCService,
    IPCCommandRequest,
    IPCHandlerResult,
    IPCAggregateError,
    IPCAggregateResult,
)


class DefaultIPCService(IIPCService):
    """An implementation of IIPCService."""

    _default_timeout_seconds: float = 10.0

    _default_timeout_max_seconds: float = 30.0

    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._ipc_extensions: list[IIPCExtension] = []
        self._ipc_extension_keys: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = (
            set()
        )
        self._ipc_critical_handlers: set[str] = set()
        self._timeout_seconds = self._resolve_timeout_setting(
            ("ipc", "dispatch", "timeout_seconds"),
            self._default_timeout_seconds,
        )
        self._timeout_max_seconds = self._resolve_timeout_setting(
            ("ipc", "dispatch", "max_timeout_seconds"),
            self._default_timeout_max_seconds,
        )
        if self._timeout_max_seconds < self._timeout_seconds:
            self._timeout_max_seconds = self._timeout_seconds

    def _resolve_timeout_setting(
        self,
        path: tuple[str, ...],
        fallback: float,
    ) -> float:
        cursor: Any = self._config
        for token in path:
            if cursor is None:
                return fallback
            cursor = getattr(cursor, token, None)
        if cursor in [None, ""]:
            return fallback
        try:
            parsed = float(cursor)
        except (TypeError, ValueError):
            return fallback
        if parsed <= 0:
            return fallback
        return parsed

    def _resolve_timeout_seconds(self, request: IPCCommandRequest) -> float:
        timeout_seconds = request.timeout_seconds
        if timeout_seconds is None:
            return self._timeout_seconds
        try:
            parsed = float(timeout_seconds)
        except (TypeError, ValueError):
            return self._timeout_seconds
        if parsed <= 0:
            return self._timeout_seconds
        if parsed > self._timeout_max_seconds:
            return self._timeout_max_seconds
        return parsed

    @staticmethod
    def _normalize_handler_name(ext: IIPCExtension) -> str:
        return type(ext).__name__

    def _extension_key(
        self,
        ext: IIPCExtension,
    ) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        platforms = tuple(sorted(str(item) for item in ext.platforms))
        commands = tuple(sorted(str(item) for item in ext.ipc_commands))
        return (
            self._normalize_handler_name(ext),
            platforms,
            commands,
        )

    async def _run_handler(
        self,
        *,
        ext: IIPCExtension,
        request: IPCCommandRequest,
        timeout_seconds: float,
    ) -> tuple[str, IPCHandlerResult | IPCAggregateError]:
        handler_name = self._normalize_handler_name(ext)
        try:
            result = await asyncio.wait_for(
                ext.process_ipc_command(request),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return (
                "error",
                IPCAggregateError(
                    code="timeout",
                    error="Timeout waiting for IPC handler response.",
                    handler=handler_name,
                ),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return (
                "error",
                IPCAggregateError(
                    code="handler_exception",
                    error=f"Unhandled exception: {exc}",
                    handler=handler_name,
                ),
            )

        if not isinstance(result, IPCHandlerResult):
            return (
                "error",
                IPCAggregateError(
                    code="invalid_handler_result",
                    error="IPC handler returned unsupported result type.",
                    handler=handler_name,
                ),
            )

        normalized_result = IPCHandlerResult(
            handler=handler_name,
            response=result.response if isinstance(result.response, dict) else {},
            ok=bool(result.ok),
            code=result.code,
            error=result.error,
        )

        if normalized_result.ok is not True:
            return (
                "error",
                IPCAggregateError(
                    code=normalized_result.code or "handler_error",
                    error=normalized_result.error or "IPC handler returned an error.",
                    handler=handler_name,
                ),
            )
        return ("result", normalized_result)

    async def handle_ipc_request(self, request: IPCCommandRequest) -> IPCAggregateResult:
        started = perf_counter()
        command = request.command
        platform = request.platform
        handlers: list[IIPCExtension] = []
        for ext in self._ipc_extensions:
            if not ext.platform_supported(platform):
                continue
            if command in ext.ipc_commands:
                handlers.append(ext)

        if not handlers:
            duration_ms = int(max(0, (perf_counter() - started) * 1000))
            return IPCAggregateResult(
                platform=platform,
                command=command,
                expected_handlers=0,
                received=1,
                duration_ms=duration_ms,
                results=[],
                errors=[
                    IPCAggregateError(
                        code="not_found",
                        error="Not Found",
                        handler=None,
                    )
                ],
            )

        timeout_seconds = self._resolve_timeout_seconds(request)
        task_results = await asyncio.gather(
            *[
                self._run_handler(
                    ext=ext,
                    request=request,
                    timeout_seconds=timeout_seconds,
                )
                for ext in handlers
            ],
            return_exceptions=False,
        )

        results: list[IPCHandlerResult] = []
        errors: list[IPCAggregateError] = []
        for item_type, item in task_results:
            if item_type == "result":
                results.append(item)
            else:
                errors.append(item)

        duration_ms = int(max(0, (perf_counter() - started) * 1000))
        return IPCAggregateResult(
            platform=platform,
            command=command,
            expected_handlers=len(handlers),
            received=len(results) + len(errors),
            duration_ms=duration_ms,
            results=results,
            errors=errors,
        )

    def bind_ipc_extension(
        self,
        ext: IIPCExtension,
        *,
        critical: bool = False,
    ) -> None:
        if ext in self._ipc_extensions:
            raise ValueError("IPC extension already registered (instance duplicate).")
        ext_key = self._extension_key(ext)
        if ext_key in self._ipc_extension_keys:
            raise ValueError(
                "IPC extension already registered (logical duplicate)."
            )
        self._ipc_extension_keys.add(ext_key)
        self._ipc_extensions.append(ext)
        if critical:
            self._ipc_critical_handlers.add(self._normalize_handler_name(ext))
