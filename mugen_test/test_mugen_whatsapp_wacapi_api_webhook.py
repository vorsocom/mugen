"""Unit tests for mugen.core.plugin.whatsapp.wacapi.api.webhook."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.service.ipc import IPCAggregateError, IPCAggregateResult
from mugen.core.plugin.whatsapp.wacapi.api import webhook
from mugen.core.plugin.whatsapp.wacapi.webhook_change import (
    WhatsAppWebhookChangeEnvelope,
    WhatsAppWebhookChangeOutcome,
    WhatsAppWebhookChangeRegistry,
)


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(verification_token: str = "token-1"):
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            webhook=SimpleNamespace(verification_token=verification_token)
        )
    )


def _event_context(
    payload: dict,
    *,
    message_change_count: int = 1,
    change_envelopes: tuple[WhatsAppWebhookChangeEnvelope, ...] = (),
) -> webhook.WhatsAppWebhookContext:
    return webhook.WhatsAppWebhookContext(
        request_id="request-id",
        payload_fingerprint="0123456789abcdef",
        filtered_payload=payload,
        message_change_count=message_change_count,
        change_envelopes=change_envelopes,
    )


def _change_envelope(
    change_field: str,
    *,
    entry_index: int = 0,
    change_index: int = 0,
    change_value: dict | None = None,
) -> WhatsAppWebhookChangeEnvelope:
    return WhatsAppWebhookChangeEnvelope.build(
        request_id="request-id",
        payload_fingerprint="0123456789abcdef",
        client_profile_id="00000000-0000-0000-0000-000000000208",
        object_type="whatsapp_business_account",
        entry_id="waba-1",
        entry_time=1234,
        entry_index=entry_index,
        change_index=change_index,
        change_field=change_field,
        change_value=change_value or {"event": "FLOW_STATUS_CHANGE"},
    )


class _ClientProfileServiceStub:
    def __init__(
        self,
        *,
        accepted_tokens: tuple[str, ...] = ("path-token", "whatsapp-path-token"),
    ) -> None:
        self._accepted_tokens = {token for token in accepted_tokens if token}

    async def resolve_active_by_identifier(self, **kwargs):
        identifier_value = kwargs.get("identifier_value")
        if identifier_value not in self._accepted_tokens:
            return None
        return SimpleNamespace(
            id="00000000-0000-0000-0000-000000000208",
            tenant_id="11111111-1111-1111-1111-111111111111",
            platform_key="whatsapp",
            profile_key="whatsapp-a",
            path_token=identifier_value,
        )

    async def build_runtime_config(self, *, config, client_profile):  # noqa: ARG002
        return config


class TestMugenWhatsAppWacapiWebhook(unittest.IsolatedAsyncioTestCase):
    """Covers webhook subscription and event endpoint branches."""

    def setUp(self) -> None:
        self._real_client_profile_service = webhook._client_profile_service
        self._client_profile_patch = patch.object(
            webhook,
            "_client_profile_service",
            return_value=_ClientProfileServiceStub(),
        )
        self._client_profile_patch.start()
        self.addCleanup(self._client_profile_patch.stop)

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            ingress_service="ingress",
            ipc_service="ipc",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
            get_ext_service=Mock(return_value="change-registry"),
        )
        with patch.object(webhook.di, "container", new=container):
            self.assertEqual(webhook._config_provider(), "cfg")
            self.assertEqual(webhook._ingress_provider(), "ingress")
            self.assertEqual(webhook._ipc_provider(), "ipc")
            self.assertEqual(webhook._logger_provider(), "logger")
            self.assertEqual(webhook._relational_storage_gateway_provider(), "rsg")
            self.assertEqual(
                webhook._change_registry_provider(),
                "change-registry",
            )

        with patch.object(
            webhook,
            "_client_profile_service",
            new=self._real_client_profile_service,
        ):
            container = SimpleNamespace(relational_storage_gateway=None)
            with patch.object(webhook.di, "container", new=container):
                self.assertIsNone(webhook._client_profile_service())

            with patch.object(
                webhook,
                "MessagingClientProfileService",
                return_value="service",
            ) as service_cls:
                container = SimpleNamespace(relational_storage_gateway="rsg")
                with patch.object(webhook.di, "container", new=container):
                    self.assertEqual(webhook._client_profile_service(), "service")
        service_cls.assert_called_once_with(
            table="admin_messaging_client_profile",
            rsg="rsg",
        )

    async def test_subscription_validation_paths(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_subscription)
        logger = Mock()

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(webhook, "request", new=SimpleNamespace(args={})),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: _make_config(),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("hub.mode incorrect.")

        logger = Mock()
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(args={"hub.mode": "subscribe"}),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: _make_config(),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with(
                "hub.verify_token not supplied or is empty."
            )

        logger = Mock()
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "expected",
                        "hub.challenge": "1234",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: _make_config(verification_token="expected"),
                    logger_provider=lambda: logger,
                    client_profile_service_provider=lambda: None,
                )
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("Could not get verification token.")

        logger = Mock()
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "expected",
                        "hub.challenge": "1234",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="missing-path-token",
                    config_provider=lambda: _make_config(verification_token="expected"),
                    logger_provider=lambda: logger,
                    client_profile_service_provider=lambda: _ClientProfileServiceStub(
                        accepted_tokens=("path-token",)
                    ),
                )
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with("Incorrect verification token.")

        logger = Mock()
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "bad-token",
                        "hub.challenge": "1234",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: _make_config(verification_token="expected"),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("Incorrect verification token.")

        logger = Mock()
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "expected",
                        "hub.challenge": "1234",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: SimpleNamespace(whatsapp=SimpleNamespace()),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("Could not get verification token.")

        logger = Mock()
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "expected",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: _make_config(verification_token="expected"),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with(
                "hub.challenge not supplied or is empty."
            )

    async def test_subscription_success(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_subscription)
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "expected",
                    "hub.challenge": "abc123",
                }
            ),
        ):
            response = await endpoint(
                path_token="path-token",
                config_provider=lambda: _make_config(verification_token="expected"),
                logger_provider=lambda: Mock(),
            )
        self.assertEqual(response, "abc123")

    async def test_event_requires_authenticated_context(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock(return_value=None))

        with patch.object(webhook, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "WhatsApp webhook authenticated context missing."
            )

    async def test_event_success_path(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="whatsapp",
                    command="whatsapp_wacapi_event",
                    expected_handlers=1,
                    received=1,
                    duration_ms=2,
                    results=[],
                    errors=[],
                )
            )
        )
        response = await endpoint(
            path_token="path-token",
            ipc_provider=lambda: ipc_service,
            logger_provider=lambda: Mock(),
            change_registry_provider=lambda: None,
            whatsapp_webhook_context=_event_context(
                {"entry": []},
                change_envelopes=(_change_envelope("messages"),),
            ),
        )

        self.assertEqual(response, {"response": "OK"})
        ipc_service.handle_ipc_request.assert_awaited_once()
        request_payload = ipc_service.handle_ipc_request.await_args.args[0]
        self.assertEqual(request_payload.platform, "whatsapp")
        self.assertEqual(request_payload.command, "whatsapp_wacapi_event")
        self.assertEqual(
            request_payload.data,
            {
                "path_token": "path-token",
                "payload": {"entry": []},
            },
        )

    async def test_event_returns_ok_and_logs_when_ipc_has_errors(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="whatsapp",
                    command="whatsapp_wacapi_event",
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
        response = await endpoint(
            path_token="path-token",
            ipc_provider=lambda: ipc_service,
            logger_provider=lambda: logger,
            whatsapp_webhook_context=_event_context({"entry": []}),
        )
        self.assertEqual(response, {"response": "OK"})
        logger.warning.assert_called_once()

    async def test_event_stages_ingress_entries_when_ipc_provider_is_absent(
        self,
    ) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        ingress_service = SimpleNamespace(stage=AsyncMock())
        entries = [object()]

        with patch.object(
            webhook,
            "extract_whatsapp_stage_entries",
            new=AsyncMock(return_value=entries),
        ) as extractor:
            response = await endpoint(
                path_token="path-token",
                ingress_provider=lambda: ingress_service,
                relational_storage_gateway_provider=lambda: "rsg",
                logger_provider=lambda: logger,
                whatsapp_webhook_context=_event_context({"entry": []}),
            )

        self.assertEqual(response, {"response": "OK"})
        extractor.assert_awaited_once()
        ingress_service.stage.assert_awaited_once_with(entries)

    async def test_event_aborts_when_ingress_staging_fails(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "extract_whatsapp_stage_entries",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    ingress_provider=lambda: SimpleNamespace(stage=AsyncMock()),
                    relational_storage_gateway_provider=lambda: "rsg",
                    logger_provider=lambda: logger,
                    whatsapp_webhook_context=_event_context({"entry": []}),
                )

        self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once()

    async def test_event_acknowledges_ignored_fields_without_dispatch(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock())
        ingress_service = SimpleNamespace(stage=AsyncMock())
        response = await endpoint(
            path_token="path-token",
            ipc_provider=lambda: ipc_service,
            ingress_provider=lambda: ingress_service,
            logger_provider=lambda: Mock(),
            whatsapp_webhook_context=_event_context(
                {"object": "whatsapp_business_account", "entry": []},
                message_change_count=0,
            ),
        )

        self.assertEqual(response, {"response": "OK"})
        ipc_service.handle_ipc_request.assert_not_awaited()
        ingress_service.stage.assert_not_awaited()

    async def test_event_dispatches_control_fields_without_phone_metadata(
        self,
    ) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        ingress_service = SimpleNamespace(stage=AsyncMock())
        registry = WhatsAppWebhookChangeRegistry()
        received: list[WhatsAppWebhookChangeEnvelope] = []

        async def handler(envelope):
            received.append(envelope)
            return WhatsAppWebhookChangeOutcome.HANDLED

        for field in (
            "flows",
            "message_template_status_update",
            "account_update",
            "phone_number_quality_update",
        ):
            registry.register_handler(handler, change_field=field)
        envelopes = tuple(
            _change_envelope(field, change_index=index)
            for index, field in enumerate(
                (
                    "flows",
                    "message_template_status_update",
                    "account_update",
                    "phone_number_quality_update",
                )
            )
        )

        response = await endpoint(
            path_token="path-token",
            ipc_provider=lambda: None,
            ingress_provider=lambda: ingress_service,
            logger_provider=lambda: logger,
            change_registry_provider=lambda: registry,
            whatsapp_webhook_context=_event_context(
                {"entry": []},
                message_change_count=0,
                change_envelopes=envelopes,
            ),
        )

        self.assertEqual(response, {"response": "OK"})
        self.assertEqual(
            [item.change_field for item in received],
            [
                "flows",
                "message_template_status_update",
                "account_update",
                "phone_number_quality_update",
            ],
        )
        ingress_service.stage.assert_not_awaited()
        self.assertEqual(logger.info.call_count, 4)
        self.assertNotIn(
            "FLOW_STATUS_CHANGE",
            " ".join(item.change_value.get("secret", "") for item in received),
        )

    async def test_event_acknowledges_no_handler_and_permanent_failure(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        registry = WhatsAppWebhookChangeRegistry()
        registry.register_handler(
            Mock(return_value=WhatsAppWebhookChangeOutcome.PERMANENT_FAILURE),
            change_field="account_update",
        )

        response = await endpoint(
            path_token="path-token",
            ipc_provider=lambda: None,
            logger_provider=lambda: logger,
            change_registry_provider=lambda: registry,
            whatsapp_webhook_context=_event_context(
                {"entry": []},
                message_change_count=0,
                change_envelopes=(
                    _change_envelope("future_field"),
                    _change_envelope("account_update", change_index=1),
                ),
            ),
        )

        self.assertEqual(response, {"response": "OK"})
        info_log = logger.info.call_args.args[0]
        warning_log = logger.warning.call_args.args[0]
        self.assertIn("reason_code=no_registered_handler", info_log)
        self.assertIn("change_field=unknown", info_log)
        self.assertIn("reason_code=permanent_handler_failure", warning_log)

    async def test_retryable_change_failure_attempts_message_ipc_then_retries(
        self,
    ) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        registry = WhatsAppWebhookChangeRegistry()
        retryable_handler = Mock(
            return_value=WhatsAppWebhookChangeOutcome.RETRYABLE_FAILURE
        )
        messages_handler = Mock(return_value=WhatsAppWebhookChangeOutcome.HANDLED)
        registry.register_handler(retryable_handler, change_field="flows")
        registry.register_handler(messages_handler, change_field="messages")
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="whatsapp",
                    command="whatsapp_wacapi_event",
                    expected_handlers=1,
                    received=1,
                    duration_ms=1,
                    results=[],
                    errors=[],
                )
            )
        )
        context = _event_context(
            {"entry": [{"changes": [{"field": "messages", "value": {}}]}]},
            change_envelopes=(
                _change_envelope("messages"),
                _change_envelope("flows", change_index=1),
            ),
        )

        with patch.object(webhook, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as exc:
                await endpoint(
                    path_token="path-token",
                    ipc_provider=lambda: ipc_service,
                    logger_provider=lambda: logger,
                    change_registry_provider=lambda: registry,
                    whatsapp_webhook_context=context,
                )

        self.assertEqual(exc.exception.code, 500)
        retryable_handler.assert_called_once()
        messages_handler.assert_called_once()
        ipc_service.handle_ipc_request.assert_awaited_once()
        self.assertEqual(len(context.dispatch_results), 2)
        self.assertIn(
            "reason_code=retryable_handler_failure",
            logger.error.call_args.args[0],
        )

    async def test_retryable_change_failure_stages_direct_messages_then_retries(
        self,
    ) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        registry = WhatsAppWebhookChangeRegistry()
        registry.register_handler(
            Mock(return_value=WhatsAppWebhookChangeOutcome.RETRYABLE_FAILURE),
            change_field="flows",
        )
        ingress_service = SimpleNamespace(stage=AsyncMock())

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "extract_whatsapp_stage_entries",
                new=AsyncMock(return_value=["entry"]),
            ),
        ):
            with self.assertRaises(_AbortCalled) as exc:
                await endpoint(
                    path_token="path-token",
                    ipc_provider=lambda: None,
                    ingress_provider=lambda: ingress_service,
                    relational_storage_gateway_provider=lambda: "rsg",
                    logger_provider=lambda: Mock(),
                    change_registry_provider=lambda: registry,
                    whatsapp_webhook_context=_event_context(
                        {"entry": []},
                        change_envelopes=(
                            _change_envelope("messages"),
                            _change_envelope("flows", change_index=1),
                        ),
                    ),
                )

        self.assertEqual(exc.exception.code, 500)
        ingress_service.stage.assert_awaited_once_with(["entry"])

    async def test_change_dispatch_logs_are_sanitized(self) -> None:
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        logger = Mock()
        registry = WhatsAppWebhookChangeRegistry()

        def handler(_envelope):
            raise RuntimeError("secret phone 15550001111 token=abc")

        registry.register_handler(handler, change_field="flows")
        envelope = _change_envelope(
            "flows",
            change_value={
                "event": "FLOW_STATUS_CHANGE",
                "message": "customer secret",
                "access_token": "token-secret",
            },
        )

        with patch.object(webhook, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled):
                await endpoint(
                    path_token="path-secret",
                    ipc_provider=lambda: None,
                    logger_provider=lambda: logger,
                    change_registry_provider=lambda: registry,
                    whatsapp_webhook_context=_event_context(
                        {"entry": []},
                        message_change_count=0,
                        change_envelopes=(envelope,),
                    ),
                )

        log_message = logger.error.call_args.args[0]
        self.assertIn("event_type=FLOW_STATUS_CHANGE", log_message)
        for sensitive in (
            "customer secret",
            "15550001111",
            "token-secret",
            "path-secret",
            "secret phone",
        ):
            self.assertNotIn(sensitive, log_message)
