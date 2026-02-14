"""Unit tests for ops_case ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_case.contrib import contribute
from mugen.core.plugin.ops_case.service.case import CaseService
from mugen.core.plugin.ops_case.service.case_assignment import CaseAssignmentService
from mugen.core.plugin.ops_case.service.case_event import CaseEventService
from mugen.core.plugin.ops_case.service.case_link import CaseLinkService


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsCaseContribBinding(unittest.TestCase):
    """Tests ops_case declarative registration and runtime materialization."""

    def test_contrib_and_runtime_binding(self) -> None:
        """Contributor should register resources, tables, schema, and services."""
        admin_ns = AdminNs("com.test.admin")
        registry = AdminRegistry(strict_permission_decls=True)

        for verb in ("read", "create", "update", "delete", "manage"):
            registry.register_permission_type(PermissionTypeDef(admin_ns.ns, verb))
        registry.register_global_role(
            GlobalRoleDef(
                namespace=admin_ns.ns,
                name="administrator",
                display_name="Administrator",
            )
        )

        contribute(
            registry,
            admin_namespace=admin_ns.ns,
            plugin_namespace="com.test.ops_case",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        cases = registry.get_resource("OpsCases")
        events = registry.get_resource("OpsCaseEvents")
        assignments = registry.get_resource("OpsCaseAssignments")
        links = registry.get_resource("OpsCaseLinks")

        self.assertIn("ops_case_case", fake_rsg.tables)
        self.assertIn("ops_case_case_event", fake_rsg.tables)
        self.assertIn("ops_case_case_assignment", fake_rsg.tables)
        self.assertIn("ops_case_case_link", fake_rsg.tables)

        self.assertIn(cases.service_key, registry.edm_services)
        self.assertIn(events.service_key, registry.edm_services)
        self.assertIn(assignments.service_key, registry.edm_services)
        self.assertIn(links.service_key, registry.edm_services)

        self.assertIsInstance(
            registry.get_edm_service(cases.service_key),
            CaseService,
        )
        self.assertIsInstance(
            registry.get_edm_service(events.service_key),
            CaseEventService,
        )
        self.assertIsInstance(
            registry.get_edm_service(assignments.service_key),
            CaseAssignmentService,
        )
        self.assertIsInstance(
            registry.get_edm_service(links.service_key),
            CaseLinkService,
        )

        self.assertIn("triage", cases.capabilities.actions)
        self.assertIn("assign", cases.capabilities.actions)
        self.assertIn("escalate", cases.capabilities.actions)
        self.assertIn("resolve", cases.capabilities.actions)
        self.assertIn("close", cases.capabilities.actions)
        self.assertIn("reopen", cases.capabilities.actions)
        self.assertIn("cancel", cases.capabilities.actions)

        case_type = registry.schema.get_type("OPSCASE.Case")
        self.assertEqual(case_type.entity_set_name, "OpsCases")
        event_type = registry.schema.get_type("OPSCASE.CaseEvent")
        self.assertEqual(event_type.entity_set_name, "OpsCaseEvents")

