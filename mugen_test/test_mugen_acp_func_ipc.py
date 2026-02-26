"""Unit tests for mugen.core.plugin.acp.api.func_ipc."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.service.ipc import IPCAggregateResult
from mugen.core.plugin.acp.api import func_ipc


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _config(*, allowlist: list[str] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        acp=SimpleNamespace(
            ipc=SimpleNamespace(
                timeout_seconds=10.0,
                max_timeout_seconds=20.0,
                allowed_commands=allowlist
                if allowlist is not None
                else ["matrix:ping"],
            )
        )
    )


def _result() -> IPCAggregateResult:
    return IPCAggregateResult(
        platform="matrix",
        command="ping",
        expected_handlers=1,
        received=1,
        duration_ms=2,
        results=[],
        errors=[],
    )


class TestMugenAcpFuncIpc(unittest.IsolatedAsyncioTestCase):
    """Covers request validation and IPC response handling paths."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            ipc_service="ipc-svc",
            logging_gateway="logger",
        )
        with patch.object(func_ipc.di, "container", new=container):
            self.assertEqual(func_ipc._config_provider(), "cfg")
            self.assertEqual(func_ipc._ipc_provider(), "ipc-svc")
            self.assertEqual(func_ipc._logger_provider(), "logger")

    async def test_ipc_webhook_validation_paths(self) -> None:
        endpoint = func_ipc.ipc_webhook.__wrapped__
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(return_value=_result())
        )
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
                    config_provider=lambda: _config(),
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
                new=SimpleNamespace(
                    get_json=AsyncMock(return_value={"platform": "matrix"})
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=lambda: _config(),
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with(
                "Missing/invalid command in IPC webhook payload."
            )

        logger = Mock()
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
                            "data": [],
                        }
                    )
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=lambda: _config(),
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with("Invalid IPC data payload.")

        logger = Mock()
        with (
            patch.object(func_ipc, "abort", side_effect=_abort_raiser),
            patch.object(
                func_ipc,
                "request",
                new=SimpleNamespace(
                    get_json=AsyncMock(
                        return_value={
                            "platform": "",
                            "command": "ping",
                        }
                    )
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=lambda: _config(),
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with(
                "Missing/invalid platform in IPC webhook payload."
            )

    async def test_ipc_webhook_denies_disallowed_command(self) -> None:
        endpoint = func_ipc.ipc_webhook.__wrapped__
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(return_value=_result())
        )
        logger = Mock()

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
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=lambda: _config(
                        allowlist=["whatsapp:whatsapp_wacapi_event"]
                    ),
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                    auth_user="user-id",
                )
            self.assertEqual(ex.exception.code, 403)

    async def test_ipc_webhook_timeout_parse_validation(self) -> None:
        endpoint = func_ipc.ipc_webhook.__wrapped__
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(return_value=_result())
        )
        logger = Mock()
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
                            "timeout_seconds": "bad",
                        }
                    )
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    config_provider=lambda: _config(),
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with(
                "Missing parameter(s) in IPC webhook payload."
            )

    async def test_ipc_webhook_success_path(self) -> None:
        endpoint = func_ipc.ipc_webhook.__wrapped__
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(return_value=_result())
        )
        logger = Mock()
        with patch.object(
            func_ipc,
            "request",
            new=SimpleNamespace(
                get_json=AsyncMock(
                    return_value={
                        "platform": "matrix",
                        "command": "ping",
                        "data": {"k": "v"},
                        "timeout_seconds": 99,
                    }
                )
            ),
        ):
            response = await endpoint(
                config_provider=lambda: _config(),
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
                auth_user="user-id",
            )
        self.assertEqual(response["response"]["platform"], "matrix")
        self.assertEqual(response["response"]["command"], "ping")
        ipc_service.handle_ipc_request.assert_awaited_once()
        request_payload = ipc_service.handle_ipc_request.await_args.args[0]
        self.assertEqual(request_payload.platform, "matrix")
        self.assertEqual(request_payload.command, "ping")
        self.assertEqual(request_payload.data, {"k": "v"})
        self.assertEqual(request_payload.timeout_seconds, 20.0)

    def test_command_allow_list_and_timeout_helpers(self) -> None:
        cfg = SimpleNamespace(
            acp=SimpleNamespace(
                ipc=SimpleNamespace(
                    allowed_commands=[],
                    timeout_seconds=15.0,
                    max_timeout_seconds=5.0,
                )
            )
        )
        self.assertFalse(
            func_ipc._command_allowed(  # pylint: disable=protected-access
                cfg,
                platform="matrix",
                command="ping",
            )
        )

        cfg.acp.ipc.allowed_commands = "invalid"
        self.assertFalse(
            func_ipc._command_allowed(  # pylint: disable=protected-access
                cfg,
                platform="matrix",
                command="ping",
            )
        )

        self.assertEqual(
            func_ipc._resolve_timeout_seconds(  # pylint: disable=protected-access
                cfg,
                None,
            ),
            15.0,
        )
        self.assertEqual(
            func_ipc._resolve_timeout_seconds(  # pylint: disable=protected-access
                cfg,
                50,
            ),
            15.0,
        )
        self.assertEqual(
            func_ipc._resolve_timeout_seconds(  # pylint: disable=protected-access
                cfg,
                4.0,
            ),
            4.0,
        )
        self.assertEqual(
            func_ipc._coerce_positive_float(  # pylint: disable=protected-access
                0,
                fallback=9.0,
            ),
            9.0,
        )
