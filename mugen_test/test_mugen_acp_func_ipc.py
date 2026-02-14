"""Unit tests for mugen.core.plugin.acp.api.func_ipc."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.acp.api import func_ipc


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


class TestMugenAcpFuncIpc(unittest.IsolatedAsyncioTestCase):
    """Covers request validation and IPC response handling paths."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            ipc_service="ipc-svc",
            logging_gateway="logger",
        )
        with patch.object(func_ipc.di, "container", new=container):
            self.assertEqual(func_ipc._ipc_provider(), "ipc-svc")
            self.assertEqual(func_ipc._logger_provider(), "logger")

    async def test_ipc_webhook_validation_paths(self) -> None:
        endpoint = func_ipc.ipc_webhook.__wrapped__
        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock())
        logger = Mock()

        with (
            patch.object(func_ipc, "abort", side_effect=_abort_raiser),
            patch.object(
                func_ipc,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value=[])),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with("`data` is not a dict.")

        logger = Mock()
        with (
            patch.object(func_ipc, "abort", side_effect=_abort_raiser),
            patch.object(
                func_ipc,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value={"platform": "matrix"})),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with("Missing parameter(s) in IPC webhook payload.")

    async def test_ipc_webhook_timeout_and_success_paths(self) -> None:
        endpoint = func_ipc.ipc_webhook.__wrapped__

        async def _enqueue_response(_platform: str, payload: dict):
            await payload["response_queue"].put({"response": {"ok": True}})

        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock(side_effect=_enqueue_response))
        logger = Mock()
        with patch.object(
            func_ipc,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(
                    return_value={
                        "platform": "matrix",
                        "command": "ping",
                    }
                )
            ),
        ):
            response = await endpoint(
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )
        self.assertEqual(response, {"response": {"ok": True}})
        ipc_service.handle_ipc_request.assert_awaited_once()

        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock(return_value=None))
        logger = Mock()

        async def _timeout(_awaitable, timeout: float):
            _ = timeout
            _awaitable.close()
            raise asyncio.TimeoutError()

        with (
            patch.object(func_ipc, "abort", side_effect=_abort_raiser),
            patch.object(
                func_ipc,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(
                        return_value={
                            "platform": "matrix",
                            "command": "ping",
                        }
                    )
                ),
            ),
            patch("mugen.core.plugin.acp.api.func_ipc.asyncio.wait_for", new=_timeout),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 504)
            logger.error.assert_called_once_with(
                "Timed out waiting for IPC response on 'matrix'."
            )
