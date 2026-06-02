"""Validation tests for channel_orchestration ACP payload models."""

from pathlib import Path
from types import ModuleType
import sys
import unittest
import uuid

from pydantic import ValidationError


def _bootstrap_namespace_packages() -> None:
    root = Path(__file__).resolve().parents[1] / "mugen"

    if "mugen" not in sys.modules:
        mugen_pkg = ModuleType("mugen")
        mugen_pkg.__path__ = [str(root)]
        sys.modules["mugen"] = mugen_pkg

    if "mugen.core" not in sys.modules:
        core_pkg = ModuleType("mugen.core")
        core_pkg.__path__ = [str(root / "core")]
        sys.modules["mugen.core"] = core_pkg
        setattr(sys.modules["mugen"], "core", core_pkg)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.channel_orchestration.api.validation import (
    ActivateHandoffValidation,
    DeactivateHandoffValidation,
    HumanReplyValidation,
    ListTranscriptValidation,
    IngressBindingCreateValidation,
    RoutingRuleCreateValidation,
)


class TestMugenChannelOrchestrationValidation(unittest.TestCase):
    """Covers validation behavior for channel orchestration payload schemas."""

    def test_ingress_binding_create_validation_accepts_optional_profile(self) -> None:
        tenant_id = uuid.uuid4()
        channel_profile_id = uuid.uuid4()

        payload = IngressBindingCreateValidation(
            TenantId=tenant_id,
            ChannelProfileId=channel_profile_id,
            ChannelKey=" whatsapp ",
            IdentifierType=" phone_number_id ",
            IdentifierValue=" 1234567890 ",
        )

        self.assertEqual(payload.tenant_id, tenant_id)
        self.assertEqual(payload.channel_profile_id, channel_profile_id)
        self.assertEqual(payload.channel_key, "whatsapp")
        self.assertEqual(payload.identifier_type, "phone_number_id")
        self.assertEqual(payload.identifier_value, "1234567890")

        payload_without_profile = IngressBindingCreateValidation(
            TenantId=tenant_id,
            ChannelKey="whatsapp",
            IdentifierType="phone_number_id",
            IdentifierValue="1234567890",
        )
        self.assertIsNone(payload_without_profile.channel_profile_id)

    def test_ingress_binding_create_validation_rejects_empty_required_text(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()

        with self.assertRaises(ValidationError):
            IngressBindingCreateValidation(
                TenantId=tenant_id,
                ChannelKey="   ",
                IdentifierType="phone_number_id",
                IdentifierValue="1234567890",
            )

        with self.assertRaises(ValidationError):
            IngressBindingCreateValidation(
                TenantId=tenant_id,
                ChannelKey="whatsapp",
                IdentifierType="   ",
                IdentifierValue="1234567890",
            )

        with self.assertRaises(ValidationError):
            IngressBindingCreateValidation(
                TenantId=tenant_id,
                ChannelKey="whatsapp",
                IdentifierType="phone_number_id",
                IdentifierValue="   ",
            )

    def test_handoff_validators_normalize_and_reject_invalid_payloads(self) -> None:
        client_profile_id = uuid.uuid4()

        activate = ActivateHandoffValidation(
            Platform=" matrix ",
            ChannelId=" channel ",
            RoomId=" room ",
            SenderId=" sender ",
            ConversationId=" conversation ",
            ClientProfileId=client_profile_id,
            ServiceRouteKey=" support ",
            Reason=" agent requested help ",
            Metadata={"k": "v"},
        )
        self.assertEqual(activate.platform, "matrix")
        self.assertEqual(activate.channel_id, "channel")
        self.assertEqual(activate.room_id, "room")
        self.assertEqual(activate.sender_id, "sender")
        self.assertEqual(activate.conversation_id, "conversation")
        self.assertEqual(activate.client_profile_id, client_profile_id)
        self.assertEqual(activate.service_route_key, "support")
        self.assertEqual(activate.reason, "agent requested help")
        self.assertEqual(activate.metadata, {"k": "v"})

        with self.assertRaisesRegex(ValidationError, "Platform must be non-empty."):
            ActivateHandoffValidation(
                Platform=" ",
                RoomId="room",
                SenderId="sender",
            )

        with self.assertRaisesRegex(ValidationError, "Content must be non-empty."):
            HumanReplyValidation(Content="   ")

        reply = HumanReplyValidation(
            Content=" answer ",
            MessageId=" reply-1 ",
            TraceId=" trace-1 ",
        )
        self.assertEqual(reply.content, "answer")
        self.assertEqual(reply.message_id, "reply-1")
        self.assertEqual(reply.trace_id, "trace-1")

        deactivate = DeactivateHandoffValidation()
        self.assertIsNone(deactivate.reason)

        deactivate_with_reason = DeactivateHandoffValidation(Reason=" done ")
        self.assertEqual(deactivate_with_reason.reason, "done")

        self.assertEqual(ListTranscriptValidation(Limit=25).limit, 25)
        with self.assertRaises(ValidationError):
            ListTranscriptValidation(Limit=0)

    def test_routing_rule_create_validation_accepts_target_variants(self) -> None:
        tenant_id = uuid.uuid4()
        channel_profile_id = uuid.uuid4()
        owner_user_id = uuid.uuid4()

        queue_payload = RoutingRuleCreateValidation(
            TenantId=tenant_id,
            ChannelProfileId=channel_profile_id,
            RouteKey=" support ",
            TargetQueueName=" frontline ",
            TargetNamespace=" contact-center ",
            Priority=0,
            IsActive=True,
            Attributes={"tier": "gold"},
        )
        self.assertEqual(queue_payload.tenant_id, tenant_id)
        self.assertEqual(queue_payload.channel_profile_id, channel_profile_id)
        self.assertEqual(queue_payload.route_key, "support")
        self.assertEqual(queue_payload.target_queue_name, "frontline")
        self.assertEqual(queue_payload.target_namespace, "contact-center")
        self.assertEqual(queue_payload.priority, 0)
        self.assertTrue(queue_payload.is_active)
        self.assertEqual(queue_payload.attributes, {"tier": "gold"})

        owner_payload = RoutingRuleCreateValidation(
            TenantId=tenant_id,
            RouteKey="owner",
            OwnerUserId=owner_user_id,
        )
        self.assertEqual(owner_payload.owner_user_id, owner_user_id)

        service_payload = RoutingRuleCreateValidation(
            TenantId=tenant_id,
            RouteKey="service",
            TargetServiceKey=" handoff.service ",
        )
        self.assertEqual(service_payload.target_service_key, "handoff.service")

    def test_routing_rule_create_validation_rejects_invalid_payloads(self) -> None:
        tenant_id = uuid.uuid4()

        with self.assertRaisesRegex(
            ValidationError,
            "Provide TargetQueueName, OwnerUserId, or TargetServiceKey.",
        ):
            RoutingRuleCreateValidation(
                TenantId=tenant_id,
                RouteKey="support",
            )

        with self.assertRaisesRegex(ValidationError, "RouteKey must be non-empty."):
            RoutingRuleCreateValidation(
                TenantId=tenant_id,
                RouteKey="   ",
                TargetQueueName="frontline",
            )

        with self.assertRaisesRegex(
            ValidationError,
            "TargetQueueName must be non-empty when provided.",
        ):
            RoutingRuleCreateValidation(
                TenantId=tenant_id,
                RouteKey="support",
                TargetQueueName="   ",
            )

        with self.assertRaises(ValidationError) as ex:
            RoutingRuleCreateValidation(
                TenantId=tenant_id,
                RouteKey="support",
                TargetQueueName="frontline",
                Priority=-1,
            )
        self.assertIn("greater than or equal to 0", str(ex.exception))
