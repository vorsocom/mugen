"""Unit tests for mugen.core.service.ipc.DefaultIPCService."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.contract.service.ipc import (
    IPCCommandRequest,
    IPCHandlerResult,
    IPCAggregateError,
    IPCAggregateResult,
)
from mugen.core.service.ipc import DefaultIPCService


class _DummyIpcExt:
    def __init__(self, *, platforms, ipc_commands, processor):
        self.platforms = platforms
        self.ipc_commands = ipc_commands
        self.process_ipc_command = processor

    def platform_supported(self, platform: str) -> bool:
        return not self.platforms or platform in self.platforms


class TestMugenServiceIPC(unittest.IsolatedAsyncioTestCase):
    """Tests IPC fanout, aggregation, and failure paths."""

    def _new_service(self) -> DefaultIPCService:
        return DefaultIPCService(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )

    async def test_no_matching_handlers_returns_not_found(self) -> None:
        svc = self._new_service()

        response = await svc.handle_ipc_request(
            IPCCommandRequest(
                platform="matrix",
                command="unknown",
            )
        )

        self.assertEqual(response.platform, "matrix")
        self.assertEqual(response.command, "unknown")
        self.assertEqual(response.expected_handlers, 0)
        self.assertEqual(response.received, 1)
        self.assertEqual(response.results, [])
        self.assertEqual(len(response.errors), 1)
        self.assertEqual(response.errors[0].code, "not_found")

    async def test_matching_handlers_aggregate_results(self) -> None:
        svc = self._new_service()

        async def handler_a(_request):
            return IPCHandlerResult(
                handler="should_be_overwritten",
                response={"ok": "a"},
            )

        async def handler_b(_request):
            return IPCHandlerResult(
                handler="should_be_overwritten",
                response={"ok": "b"},
            )

        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["ping"],
                processor=handler_a,
            )
        )
        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=[],
                ipc_commands=["ping"],
                processor=handler_b,
            )
        )
        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=["whatsapp"],
                ipc_commands=["ping"],
                processor=handler_b,
            )
        )
        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["other"],
                processor=handler_b,
            )
        )

        response = await svc.handle_ipc_request(
            IPCCommandRequest(
                platform="matrix",
                command="ping",
            )
        )

        self.assertEqual(response.expected_handlers, 2)
        self.assertEqual(response.received, 2)
        self.assertEqual(len(response.errors), 0)
        self.assertEqual(len(response.results), 2)
        handlers = {item.handler for item in response.results}
        self.assertEqual(handlers, {"_DummyIpcExt"})

    async def test_handler_exception_is_returned_as_error(self) -> None:
        svc = self._new_service()

        async def crash(_request):
            raise RuntimeError("boom")

        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["ping"],
                processor=crash,
            )
        )

        response = await svc.handle_ipc_request(
            IPCCommandRequest(
                platform="matrix",
                command="ping",
            )
        )

        self.assertEqual(response.expected_handlers, 1)
        self.assertEqual(response.received, 1)
        self.assertEqual(response.results, [])
        self.assertEqual(len(response.errors), 1)
        self.assertEqual(response.errors[0].code, "handler_exception")
        self.assertIn("Unhandled exception: boom", response.errors[0].error)

    async def test_timeout_returns_error(self) -> None:
        svc = self._new_service()

        async def never_responds(_request):
            await asyncio.sleep(60)
            return IPCHandlerResult(handler="unused", response={})

        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["ping"],
                processor=never_responds,
            )
        )

        async def _timeout_and_close(awaitable, timeout):
            _ = timeout
            awaitable.close()
            raise asyncio.TimeoutError()

        with patch("mugen.core.service.ipc.asyncio.wait_for", new=_timeout_and_close):
            response = await svc.handle_ipc_request(
                IPCCommandRequest(
                    platform="matrix",
                    command="ping",
                )
            )

        self.assertEqual(response.expected_handlers, 1)
        self.assertEqual(response.received, 1)
        self.assertEqual(response.results, [])
        self.assertEqual(len(response.errors), 1)
        self.assertEqual(response.errors[0].code, "timeout")

    async def test_duplicate_registration_is_rejected(self) -> None:
        svc = self._new_service()

        async def handler(_request):
            return IPCHandlerResult(handler="x", response={})

        ext = _DummyIpcExt(
            platforms=["matrix"],
            ipc_commands=["ping"],
            processor=handler,
        )
        svc.bind_ipc_extension(ext)

        with self.assertRaises(ValueError):
            svc.bind_ipc_extension(ext)

    async def test_logical_duplicate_registration_is_rejected(self) -> None:
        svc = self._new_service()

        async def handler(_request):
            return IPCHandlerResult(handler="x", response={})

        first_ext = _DummyIpcExt(
            platforms=["matrix"],
            ipc_commands=["ping"],
            processor=handler,
        )
        second_ext = _DummyIpcExt(
            platforms=["matrix"],
            ipc_commands=["ping"],
            processor=handler,
        )
        svc.bind_ipc_extension(first_ext)

        with self.assertRaises(ValueError):
            svc.bind_ipc_extension(second_ext)

    async def test_bind_ipc_extension_tracks_critical_handlers(self) -> None:
        svc = self._new_service()

        async def handler(_request):
            return IPCHandlerResult(handler="x", response={})

        ext = _DummyIpcExt(
            platforms=["matrix"],
            ipc_commands=["ping"],
            processor=handler,
        )
        svc.bind_ipc_extension(ext, critical=True)
        self.assertIn("_DummyIpcExt", svc._ipc_critical_handlers)  # pylint: disable=protected-access

    async def test_timeout_setting_resolution_paths(self) -> None:
        config = SimpleNamespace(
            ipc=SimpleNamespace(
                dispatch=SimpleNamespace(
                    timeout_seconds="bad",
                    max_timeout_seconds=0,
                )
            )
        )
        svc = DefaultIPCService(
            config=config,
            logging_gateway=Mock(),
        )
        self.assertEqual(svc._timeout_seconds, 10.0)  # pylint: disable=protected-access
        self.assertEqual(svc._timeout_max_seconds, 30.0)  # pylint: disable=protected-access

        config = SimpleNamespace(
            ipc=SimpleNamespace(
                dispatch=SimpleNamespace(
                    timeout_seconds="",
                    max_timeout_seconds=None,
                )
            )
        )
        svc = DefaultIPCService(
            config=config,
            logging_gateway=Mock(),
        )
        self.assertEqual(svc._timeout_seconds, 10.0)  # pylint: disable=protected-access
        self.assertEqual(svc._timeout_max_seconds, 30.0)  # pylint: disable=protected-access

        config = SimpleNamespace(
            ipc=SimpleNamespace(
                dispatch=SimpleNamespace(
                    timeout_seconds=12.0,
                    max_timeout_seconds=5.0,
                )
            )
        )
        svc = DefaultIPCService(
            config=config,
            logging_gateway=Mock(),
        )
        self.assertEqual(svc._timeout_seconds, 12.0)  # pylint: disable=protected-access
        self.assertEqual(svc._timeout_max_seconds, 12.0)  # pylint: disable=protected-access

    async def test_request_timeout_resolution_paths(self) -> None:
        config = SimpleNamespace(
            ipc=SimpleNamespace(
                dispatch=SimpleNamespace(
                    timeout_seconds=10.0,
                    max_timeout_seconds=20.0,
                )
            )
        )
        svc = DefaultIPCService(
            config=config,
            logging_gateway=Mock(),
        )

        self.assertEqual(
            svc._resolve_timeout_seconds(  # pylint: disable=protected-access
                IPCCommandRequest(
                    platform="matrix",
                    command="ping",
                    timeout_seconds="bad",  # type: ignore[arg-type]
                )
            ),
            10.0,
        )
        self.assertEqual(
            svc._resolve_timeout_seconds(  # pylint: disable=protected-access
                IPCCommandRequest(
                    platform="matrix",
                    command="ping",
                    timeout_seconds=0,
                )
            ),
            10.0,
        )
        self.assertEqual(
            svc._resolve_timeout_seconds(  # pylint: disable=protected-access
                IPCCommandRequest(
                    platform="matrix",
                    command="ping",
                    timeout_seconds=999,
                )
            ),
            20.0,
        )
        self.assertEqual(
            svc._resolve_timeout_seconds(  # pylint: disable=protected-access
                IPCCommandRequest(
                    platform="matrix",
                    command="ping",
                    timeout_seconds=4.5,
                )
            ),
            4.5,
        )

    async def test_invalid_result_and_handler_error_result_are_aggregated(self) -> None:
        svc = self._new_service()

        async def invalid_result(_request):
            return {"bad": "payload"}

        async def handler_error(_request):
            return IPCHandlerResult(
                handler="x",
                ok=False,
            )

        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["ping"],
                processor=invalid_result,
            )
        )
        svc.bind_ipc_extension(
            _DummyIpcExt(
                platforms=[],
                ipc_commands=["ping"],
                processor=handler_error,
            )
        )

        response = await svc.handle_ipc_request(
            IPCCommandRequest(
                platform="matrix",
                command="ping",
            )
        )
        error_codes = sorted(item.code for item in response.errors)
        self.assertEqual(error_codes, ["handler_error", "invalid_handler_result"])

    async def test_ipc_model_to_dict_helpers(self) -> None:
        handler = IPCHandlerResult(
            handler="handler-a",
            response={"ok": True},
            ok=False,
            code="handler_error",
            error="failed",
        )
        self.assertEqual(
            handler.to_dict(),
            {
                "handler": "handler-a",
                "ok": False,
                "code": "handler_error",
                "error": "failed",
                "response": {"ok": True},
            },
        )
        error = IPCAggregateError(
            code="timeout",
            error="Timed out",
            handler="handler-a",
        )
        self.assertEqual(
            error.to_dict(),
            {
                "code": "timeout",
                "error": "Timed out",
                "handler": "handler-a",
            },
        )
        aggregate = IPCAggregateResult(
            platform="matrix",
            command="ping",
            expected_handlers=1,
            received=1,
            duration_ms=1,
            results=[handler],
            errors=[error],
        )
        payload = aggregate.to_dict()
        self.assertEqual(payload["results"][0]["handler"], "handler-a")
        self.assertEqual(payload["errors"][0]["code"], "timeout")
