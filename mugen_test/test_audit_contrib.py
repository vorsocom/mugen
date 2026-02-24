"""Focused tests for audit contributor defaults."""

from pathlib import Path
from types import ModuleType
import sys
import unittest
import unittest.mock


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
from mugen.core.plugin.audit.api.validation import (
    AuditEventPlaceLegalHoldValidation,
    AuditEventRunLifecycleValidation,
    AuditEventSealBacklogValidation,
    AuditEventVerifyChainValidation,
)
from mugen.core.plugin.audit.contrib import contribute


class TestAuditContrib(unittest.TestCase):
    """Tests for audit contributor registration behavior."""

    def test_audit_resource_registers_manage_actions(self):
        registry = unittest.mock.Mock()

        contribute(
            registry,
            admin_namespace="com.vorsocomputing.mugen.acp",
            plugin_namespace="com.vorsocomputing.mugen.audit",
        )

        resource = registry.register_resource.call_args.args[0]

        self.assertTrue(resource.capabilities.allow_read)
        self.assertFalse(resource.capabilities.allow_create)
        self.assertFalse(resource.capabilities.allow_update)
        self.assertFalse(resource.capabilities.allow_delete)
        self.assertTrue(resource.capabilities.allow_manage)
        self.assertEqual(resource.entity_set, "AuditEvents")
        self.assertEqual(resource.edm_type_name, "AUDIT.AuditEvent")
        self.assertIn("place_legal_hold", resource.capabilities.actions)
        self.assertIn("run_lifecycle", resource.capabilities.actions)
        self.assertIn("verify_chain", resource.capabilities.actions)
        self.assertIn("seal_backlog", resource.capabilities.actions)
        self.assertIs(
            resource.capabilities.actions["place_legal_hold"]["schema"],
            AuditEventPlaceLegalHoldValidation,
        )
        self.assertIs(
            resource.capabilities.actions["run_lifecycle"]["schema"],
            AuditEventRunLifecycleValidation,
        )
        self.assertIs(
            resource.capabilities.actions["verify_chain"]["schema"],
            AuditEventVerifyChainValidation,
        )
        self.assertIs(
            resource.capabilities.actions["seal_backlog"]["schema"],
            AuditEventSealBacklogValidation,
        )
