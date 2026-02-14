"""Unit tests for mugen.core.service.ipc.DefaultIPCService."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.service.ipc import DefaultIPCService


class _DummyIpcExt:
    def __init__(self, *, platforms, ipc_commands, processor):
        self.platforms = platforms
        self.ipc_commands = ipc_commands
        self.process_ipc_command = processor


class TestMugenServiceIPC(unittest.IsolatedAsyncioTestCase):
    """Tests IPC fanout, aggregation, and failure paths."""

    def _new_service(self) -> DefaultIPCService:
        svc = DefaultIPCService(logging_gateway=Mock())
        svc._ipc_extensions = []
        return svc

    async def test_no_matching_handlers_returns_not_found(self) -> None:
        svc = self._new_service()
        caller_q = asyncio.Queue()

        await svc.handle_ipc_request(
            "matrix",
            {"command": "unknown", "response_queue": caller_q},
        )

        payload = await caller_q.get()
        self.assertEqual(payload["response"]["command"], "unknown")
        self.assertEqual(payload["response"]["results"], [])
        self.assertEqual(payload["response"]["errors"], [{"error": "Not Found"}])

    async def test_matching_handlers_aggregate_results(self) -> None:
        svc = self._new_service()
        caller_q = asyncio.Queue()

        async def handler_a(payload):
            await payload["response_queue"].put(
                {"handler": payload["handler"], "response": {"ok": "a"}}
            )

        async def handler_b(payload):
            await payload["response_queue"].put(
                {"handler": payload["handler"], "response": {"ok": "b"}}
            )

        svc.register_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["ping"],
                processor=handler_a,
            )
        )
        svc.register_ipc_extension(
            _DummyIpcExt(
                platforms=[],
                ipc_commands=["ping"],
                processor=handler_b,
            )
        )
        svc.register_ipc_extension(
            _DummyIpcExt(
                platforms=["whatsapp"],
                ipc_commands=["ping"],
                processor=AsyncMock(),
            )
        )
        svc.register_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["other"],
                processor=AsyncMock(),
            )
        )

        await svc.handle_ipc_request(
            "matrix",
            {"command": "ping", "response_queue": caller_q},
        )

        payload = await caller_q.get()
        response = payload["response"]
        self.assertEqual(response["expected_handlers"], 2)
        self.assertEqual(response["received"], 2)
        self.assertEqual(len(response["errors"]), 0)
        self.assertEqual(len(response["results"]), 2)
        handlers = {item["handler"] for item in response["results"]}
        self.assertEqual(handlers, {"_DummyIpcExt"})

    async def test_handler_exception_is_returned_as_error(self) -> None:
        svc = self._new_service()
        caller_q = asyncio.Queue()

        async def crash(_payload):
            raise RuntimeError("boom")

        svc.register_ipc_extension(
            _DummyIpcExt(
                platforms=["matrix"],
                ipc_commands=["ping"],
                processor=crash,
            )
        )

        await svc.handle_ipc_request(
            "matrix",
            {"command": "ping", "response_queue": caller_q},
        )

        payload = await caller_q.get()
        response = payload["response"]
        self.assertEqual(response["expected_handlers"], 1)
        self.assertEqual(response["received"], 1)
        self.assertEqual(response["results"], [])
        self.assertEqual(len(response["errors"]), 1)
        self.assertEqual(response["errors"][0]["ok"], False)
        self.assertIn("Unhandled exception: boom", response["errors"][0]["error"])

    async def test_timeout_returns_error(self) -> None:
        svc = self._new_service()
        caller_q = asyncio.Queue()

        async def never_responds(_payload):
            await asyncio.sleep(60)

        svc.register_ipc_extension(
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
            await svc.handle_ipc_request(
                "matrix",
                {"command": "ping", "response_queue": caller_q},
            )

        payload = await caller_q.get()
        response = payload["response"]
        self.assertEqual(response["expected_handlers"], 1)
        self.assertEqual(response["received"], 1)
        self.assertEqual(response["results"], [])
        self.assertEqual(
            response["errors"],
            [{"error": "Timeout waiting for IPC handler response"}],
        )
