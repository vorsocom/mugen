"""Tests for authenticated WhatsApp webhook change dispatch contracts."""

import asyncio
from types import MappingProxyType
import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.plugin.whatsapp.wacapi.webhook_change import (
    WhatsAppWebhookChangeEnvelope,
    WhatsAppWebhookChangeOutcome,
    WhatsAppWebhookChangeRegistry,
    normalize_webhook_change_field,
    safe_webhook_change_field,
)


def _envelope(
    *,
    change_field: str = "flows",
    change_value: dict | None = None,
    entry_id: object = "waba-1",
    entry_time: object = 1234,
) -> WhatsAppWebhookChangeEnvelope:
    return WhatsAppWebhookChangeEnvelope.build(
        request_id="request-1",
        payload_fingerprint="0123456789abcdef",
        client_profile_id="00000000-0000-0000-0000-000000000401",
        object_type="whatsapp_business_account",
        entry_id=entry_id,
        entry_time=entry_time,
        entry_index=2,
        change_index=3,
        change_field=change_field,
        change_value=change_value
        or {
            "event": "FLOW_STATUS_CHANGE",
            "nested": {"status": "BLOCKED"},
            "items": [{"id": "flow-secret"}],
        },
    )


class TestMugenWhatsAppWacapiWebhookChange(unittest.IsolatedAsyncioTestCase):
    """Covers envelope normalization and deterministic handler dispatch."""

    def test_field_normalization_and_safe_dimensions(self) -> None:
        self.assertEqual(normalize_webhook_change_field(" flows "), "flows")
        self.assertEqual(
            normalize_webhook_change_field("*", allow_wildcard=True),
            "*",
        )
        self.assertEqual(safe_webhook_change_field("messages"), "messages")
        self.assertEqual(safe_webhook_change_field("future_field"), "unknown")
        self.assertEqual(safe_webhook_change_field(None), "unknown")
        for invalid in (None, "", "bad-field", "A_FIELD", "a" * 129, "*"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_webhook_change_field(invalid)

    def test_envelope_is_normalized_and_deeply_immutable(self) -> None:
        envelope = _envelope()

        self.assertEqual(envelope.entry_id, "waba-1")
        self.assertEqual(envelope.entry_time, 1234)
        self.assertEqual(envelope.entry_index, 2)
        self.assertEqual(envelope.change_index, 3)
        self.assertIsInstance(envelope.change_value, MappingProxyType)
        self.assertEqual(envelope.change_value["nested"]["status"], "BLOCKED")
        self.assertIsInstance(envelope.change_value["items"], tuple)
        with self.assertRaises(TypeError):
            envelope.change_value["event"] = "CHANGED"
        with self.assertRaises(TypeError):
            envelope.change_value["nested"]["status"] = "CHANGED"
        with self.assertRaises(AttributeError):
            envelope.request_id = "changed"

        normalized = _envelope(entry_id="", entry_time=True, change_value={})
        self.assertIsNone(normalized.entry_id)
        self.assertIsNone(normalized.entry_time)
        string_time = _envelope(entry_time="1234")
        self.assertEqual(string_time.entry_time, "1234")

    def test_registry_validates_registration_and_selection(self) -> None:
        registry = WhatsAppWebhookChangeRegistry()
        handler = Mock(return_value=WhatsAppWebhookChangeOutcome.HANDLED)
        wildcard = Mock(return_value=WhatsAppWebhookChangeOutcome.IGNORED)
        registry.register_handler(handler, change_field="flows")
        registry.register_handler(wildcard, change_field="*")

        self.assertEqual(registry.handlers_for("flows"), (handler, wildcard))
        self.assertEqual(registry.handlers_for("future_field"), (wildcard,))
        with self.assertRaises(TypeError):
            registry.register_handler(None, change_field="flows")
        with self.assertRaises(ValueError):
            registry.register_handler(handler, change_field="bad-field")
        with self.assertRaises(ValueError):
            registry.handlers_for("bad-field")

    async def test_dispatch_attempts_every_handler_and_aggregates_outcomes(
        self,
    ) -> None:
        calls: list[str] = []
        registry = WhatsAppWebhookChangeRegistry()

        def handled(_event):
            calls.append("handled")
            return "handled"

        async def ignored(_event):
            calls.append("ignored")
            return WhatsAppWebhookChangeOutcome.IGNORED

        def raises(_event):
            calls.append("raises")
            raise RuntimeError("payload secret")

        def permanent(_event):
            calls.append("permanent")
            return WhatsAppWebhookChangeOutcome.PERMANENT_FAILURE

        registry.register_handler(handled, change_field="flows")
        registry.register_handler(ignored, change_field="*")
        registry.register_handler(raises, change_field="flows")
        registry.register_handler(permanent, change_field="flows")

        result = await registry.dispatch(_envelope())

        self.assertEqual(calls, ["handled", "ignored", "raises", "permanent"])
        self.assertEqual(result.safe_change_field, "flows")
        self.assertEqual(result.event_type, "FLOW_STATUS_CHANGE")
        self.assertEqual(result.handler_count, 4)
        self.assertEqual(result.handled_count, 1)
        self.assertEqual(result.ignored_count, 1)
        self.assertEqual(result.permanent_failure_count, 1)
        self.assertEqual(result.retryable_failure_count, 1)
        self.assertEqual(result.reason_code, "retryable_handler_failure")

    async def test_dispatch_reason_precedence_and_unknown_normalization(self) -> None:
        cases = (
            ((), "no_registered_handler"),
            ((WhatsAppWebhookChangeOutcome.IGNORED,), "change_handler_ignored"),
            ((WhatsAppWebhookChangeOutcome.HANDLED,), "change_handler_handled"),
            (
                (WhatsAppWebhookChangeOutcome.PERMANENT_FAILURE,),
                "permanent_handler_failure",
            ),
        )
        for outcomes, reason_code in cases:
            with self.subTest(reason_code=reason_code):
                registry = WhatsAppWebhookChangeRegistry()
                for outcome in outcomes:
                    registry.register_handler(
                        Mock(return_value=outcome),
                        change_field="future_field",
                    )
                result = await registry.dispatch(
                    _envelope(
                        change_field="future_field",
                        change_value={"event_type": "FLOW_JSON_VERSION_DEPRECATION"},
                    )
                )
                self.assertEqual(result.safe_change_field, "unknown")
                self.assertEqual(
                    result.event_type,
                    "FLOW_JSON_VERSION_DEPRECATION",
                )
                self.assertEqual(result.reason_code, reason_code)

        invalid_result_registry = WhatsAppWebhookChangeRegistry()
        invalid_result_registry.register_handler(
            Mock(return_value=None),
            change_field="future_field",
        )
        result = await invalid_result_registry.dispatch(
            _envelope(
                change_field="future_field",
                change_value={"event": "customer-controlled-secret"},
            )
        )
        self.assertEqual(result.event_type, "unknown")
        self.assertEqual(result.retryable_failure_count, 1)

    async def test_dispatch_propagates_cancellation(self) -> None:
        registry = WhatsAppWebhookChangeRegistry()
        registry.register_handler(
            AsyncMock(side_effect=asyncio.CancelledError()),
            change_field="flows",
        )

        with self.assertRaises(asyncio.CancelledError):
            await registry.dispatch(_envelope())


if __name__ == "__main__":
    unittest.main()
