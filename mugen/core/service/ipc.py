"""Provides an implementation of IIPCService."""

__all__ = ["DefaultIPCService"]

import asyncio
from typing import Any

from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService


class DefaultIPCService(IIPCService):
    """An implementation of IIPCService."""

    _ipc_extensions: list[IIPCExtension] = []

    def __init__(
        self,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._logging_gateway = logging_gateway

    async def handle_ipc_request(self, platform: str, ipc_payload: dict) -> None:
        # Process by IPC extensions.
        command = ipc_payload.get("command")
        caller_q: asyncio.Queue = ipc_payload["response_queue"]

        # 1) Identify all matching handlers
        handlers: list[IIPCExtension] = []
        for ext in self._ipc_extensions:
            if ext.platforms and platform not in ext.platforms:
                continue
            if command in ext.ipc_commands:
                handlers.append(ext)

        if not handlers:
            await caller_q.put(
                {
                    "response": {
                        "command": command,
                        "results": [],
                        "errors": [{"error": "Not Found"}],
                    }
                }
            )
            return

        # 2) Fan out using an internal queue so we can aggregate
        internal_q: asyncio.Queue = asyncio.Queue()
        timeout_s = 10.0  # choose what’s appropriate

        async def run_handler(ext: IIPCExtension) -> None:
            handler_name = type(ext).__name__
            payload = dict(ipc_payload)
            payload["response_queue"] = internal_q
            payload["handler"] = handler_name
            try:
                await ext.process_ipc_command(payload)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Ensure exactly one response even on exceptions.
                await internal_q.put(
                    {
                        "handler": handler_name,
                        "ok": False,
                        "error": f"Unhandled exception: {exc}",
                    }
                )

        tasks = [asyncio.create_task(run_handler(ext)) for ext in handlers]

        # 3) Collect up to N responses (or timeout)
        expected = len(handlers)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        async def collect_one() -> dict[str, Any]:
            return await asyncio.wait_for(internal_q.get(), timeout=timeout_s)

        for _ in range(expected):
            try:
                msg = await collect_one()
            except asyncio.TimeoutError:
                errors.append({"error": "Timeout waiting for IPC handler response"})
                break

            if msg.get("ok") is False:
                errors.append(msg)
            else:
                results.append(msg)

        # Ensure tasks are cleaned up (don’t let them leak)
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        # 4) Put a single aggregated response back to caller
        await caller_q.put(
            {
                "response": {
                    "command": command,
                    "expected_handlers": expected,
                    "received": len(results) + len(errors),
                    "results": results,  # each entry includes "handler" + "response"
                    "errors": errors,
                }
            }
        )

    def register_ipc_extension(self, ext: IIPCExtension) -> None:
        self._ipc_extensions.append(ext)
