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
    IngressBindingCreateValidation,
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
