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
    AuditBizTraceInspectTraceValidation,
    AuditCorrelationResolveTraceValidation,
    AuditEventPlaceLegalHoldValidation,
    AuditEventRunLifecycleValidation,
    AuditEventSealBacklogValidation,
    AuditEventVerifyChainValidation,
    EvidenceBlobRegisterValidation,
    EvidenceBlobVerifyHashValidation,
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

        resources = [call.args[0] for call in registry.register_resource.call_args_list]
        resources_by_set = {resource.entity_set: resource for resource in resources}

        self.assertEqual(
            set(resources_by_set.keys()),
            {
                "AuditEvents",
                "AuditCorrelationLinks",
                "AuditBizTraceEvents",
                "EvidenceBlobs",
            },
        )

        events_resource = resources_by_set["AuditEvents"]
        self.assertTrue(events_resource.capabilities.allow_read)
        self.assertFalse(events_resource.capabilities.allow_create)
        self.assertFalse(events_resource.capabilities.allow_update)
        self.assertFalse(events_resource.capabilities.allow_delete)
        self.assertTrue(events_resource.capabilities.allow_manage)
        self.assertEqual(events_resource.edm_type_name, "AUDIT.AuditEvent")
        self.assertIn("place_legal_hold", events_resource.capabilities.actions)
        self.assertIn("run_lifecycle", events_resource.capabilities.actions)
        self.assertIn("verify_chain", events_resource.capabilities.actions)
        self.assertIn("seal_backlog", events_resource.capabilities.actions)
        self.assertIs(
            events_resource.capabilities.actions["place_legal_hold"]["schema"],
            AuditEventPlaceLegalHoldValidation,
        )
        self.assertIs(
            events_resource.capabilities.actions["run_lifecycle"]["schema"],
            AuditEventRunLifecycleValidation,
        )
        self.assertIs(
            events_resource.capabilities.actions["verify_chain"]["schema"],
            AuditEventVerifyChainValidation,
        )
        self.assertIs(
            events_resource.capabilities.actions["seal_backlog"]["schema"],
            AuditEventSealBacklogValidation,
        )

        correlation_resource = resources_by_set["AuditCorrelationLinks"]
        self.assertEqual(
            correlation_resource.capabilities.actions["resolve_trace"]["schema"],
            AuditCorrelationResolveTraceValidation,
        )

        biz_trace_resource = resources_by_set["AuditBizTraceEvents"]
        self.assertEqual(
            biz_trace_resource.capabilities.actions["inspect_trace"]["schema"],
            AuditBizTraceInspectTraceValidation,
        )

        evidence_resource = resources_by_set["EvidenceBlobs"]
        self.assertEqual(
            evidence_resource.capabilities.actions["register"]["schema"],
            EvidenceBlobRegisterValidation,
        )
        self.assertEqual(
            evidence_resource.capabilities.actions["verify_hash"]["schema"],
            EvidenceBlobVerifyHashValidation,
        )
