"""Unit tests for ops_metering ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_metering.contrib import contribute
from mugen.core.plugin.ops_metering.service.meter_definition import (
    MeterDefinitionService,
)
from mugen.core.plugin.ops_metering.service.meter_policy import MeterPolicyService
from mugen.core.plugin.ops_metering.service.rated_usage import RatedUsageService
from mugen.core.plugin.ops_metering.service.usage_record import UsageRecordService
from mugen.core.plugin.ops_metering.service.usage_session import UsageSessionService


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsMeteringContribBinding(unittest.TestCase):
    """Tests ops_metering declarative registration and runtime materialization."""

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
            plugin_namespace="com.test.ops_metering",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        meter_defs = registry.get_resource("OpsMeterDefinitions")
        policies = registry.get_resource("OpsMeterPolicies")
        sessions = registry.get_resource("OpsUsageSessions")
        records = registry.get_resource("OpsUsageRecords")
        rated = registry.get_resource("OpsRatedUsages")

        self.assertIn("ops_metering_meter_definition", fake_rsg.tables)
        self.assertIn("ops_metering_meter_policy", fake_rsg.tables)
        self.assertIn("ops_metering_usage_session", fake_rsg.tables)
        self.assertIn("ops_metering_usage_record", fake_rsg.tables)
        self.assertIn("ops_metering_rated_usage", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(meter_defs.service_key),
            MeterDefinitionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(policies.service_key),
            MeterPolicyService,
        )
        self.assertIsInstance(
            registry.get_edm_service(sessions.service_key),
            UsageSessionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(records.service_key),
            UsageRecordService,
        )
        self.assertIsInstance(
            registry.get_edm_service(rated.service_key),
            RatedUsageService,
        )

        self.assertIn("start_session", sessions.capabilities.actions)
        self.assertIn("pause_session", sessions.capabilities.actions)
        self.assertIn("resume_session", sessions.capabilities.actions)
        self.assertIn("stop_session", sessions.capabilities.actions)
        self.assertIn("rate_record", records.capabilities.actions)
        self.assertIn("void_record", records.capabilities.actions)

        meter_type = registry.schema.get_type("OPSMETERING.MeterDefinition")
        self.assertEqual(meter_type.entity_set_name, "OpsMeterDefinitions")

        rated_type = registry.schema.get_type("OPSMETERING.RatedUsage")
        self.assertEqual(rated_type.entity_set_name, "OpsRatedUsages")
