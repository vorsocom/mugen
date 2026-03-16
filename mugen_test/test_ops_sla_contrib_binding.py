"""Unit tests for ops_sla ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_sla.contrib import contribute
from mugen.core.plugin.ops_sla.service.sla_breach_event import SlaBreachEventService
from mugen.core.plugin.ops_sla.service.sla_calendar import SlaCalendarService
from mugen.core.plugin.ops_sla.service.sla_clock import SlaClockService
from mugen.core.plugin.ops_sla.service.sla_policy import SlaPolicyService
from mugen.core.plugin.ops_sla.service.sla_target import SlaTargetService


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsSlaContribBinding(unittest.TestCase):
    """Tests ops_sla declarative registration and runtime materialization."""

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
            plugin_namespace="com.test.ops_sla",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        policies = registry.get_resource("OpsSlaPolicies")
        calendars = registry.get_resource("OpsSlaCalendars")
        targets = registry.get_resource("OpsSlaTargets")
        clocks = registry.get_resource("OpsSlaClocks")
        events = registry.get_resource("OpsSlaBreachEvents")

        self.assertIn("ops_sla_policy", fake_rsg.tables)
        self.assertIn("ops_sla_calendar", fake_rsg.tables)
        self.assertIn("ops_sla_target", fake_rsg.tables)
        self.assertIn("ops_sla_clock", fake_rsg.tables)
        self.assertIn("ops_sla_breach_event", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(policies.service_key),
            SlaPolicyService,
        )
        self.assertIsInstance(
            registry.get_edm_service(calendars.service_key),
            SlaCalendarService,
        )
        self.assertIsInstance(
            registry.get_edm_service(targets.service_key),
            SlaTargetService,
        )
        self.assertIsInstance(
            registry.get_edm_service(clocks.service_key),
            SlaClockService,
        )
        self.assertIsInstance(
            registry.get_edm_service(events.service_key),
            SlaBreachEventService,
        )

        self.assertIn("start_clock", clocks.capabilities.actions)
        self.assertIn("pause_clock", clocks.capabilities.actions)
        self.assertIn("resume_clock", clocks.capabilities.actions)
        self.assertIn("stop_clock", clocks.capabilities.actions)
        self.assertIn("mark_breached", clocks.capabilities.actions)

        policy_type = registry.schema.get_type("OPSSLA.SlaPolicy")
        self.assertEqual(policy_type.entity_set_name, "OpsSlaPolicies")

        breach_event_type = registry.schema.get_type("OPSSLA.SlaBreachEvent")
        self.assertEqual(breach_event_type.entity_set_name, "OpsSlaBreachEvents")
