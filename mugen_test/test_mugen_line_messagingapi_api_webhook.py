"""Unit tests for mugen.core.plugin.line.messagingapi.api.webhook."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.service.ipc import IPCAggregateError, IPCAggregateResult
from mugen.core.plugin.line.messagingapi.api import webhook


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


class TestMugenLineMessagingapiWebhook(unittest.IsolatedAsyncioTestCase):
    """Covers webhook event endpoint branches."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            ipc_service="ipc",
            logging_gateway="logger",
        )
        with patch.object(webhook.di, "container", new=container):
            self.assertEqual(webhook._config_provider(), "cfg")
            self.assertEqual(webhook._ipc_provider(), "ipc")
            self.assertEqual(webhook._logger_provider(), "logger")

    async def test_event_validation_path_for_non_dict_payload(self) -> None:
        endpoint = unwrap(webhook.line_messagingapi_webhook_event)
        logger = Mock()
        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock(return_value=None))

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(get_json=AsyncMock(return_value=[])),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.debug.assert_called_once_with("`data` is not a dict.")

    async def test_event_success_path(self) -> None:
        endpoint = unwrap(webhook.line_messagingapi_webhook_event)
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="line",
                    command="line_messagingapi_event",
                    expected_handlers=1,
                    received=1,
                    duration_ms=2,
                    results=[],
                    errors=[],
                )
            )
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value={"events": []})),
        ):
            response = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: Mock(),
            )

        self.assertEqual(response, {"response": "OK"})
        ipc_service.handle_ipc_request.assert_awaited_once()
        request_payload = ipc_service.handle_ipc_request.await_args.args[0]
        self.assertEqual(request_payload.platform, "line")
        self.assertEqual(request_payload.command, "line_messagingapi_event")
        self.assertEqual(request_payload.data, {"events": []})

    async def test_event_returns_ok_and_logs_when_ipc_has_errors(self) -> None:
        endpoint = unwrap(webhook.line_messagingapi_webhook_event)
        logger = Mock()
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="line",
                    command="line_messagingapi_event",
                    expected_handlers=1,
                    received=1,
                    duration_ms=4,
                    results=[],
                    errors=[
                        IPCAggregateError(
                            code="timeout",
                            error="Timeout waiting for IPC handler response.",
                            handler="X",
                        )
                    ],
                )
            )
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value={"events": []})),
        ):
            response = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )
        self.assertEqual(response, {"response": "OK"})
        logger.warning.assert_called_once()
