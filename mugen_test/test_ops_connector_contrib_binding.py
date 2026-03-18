"""Unit tests for ops_connector ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_connector.api.validation import (
    ConnectorInstanceUpdateValidation,
    ConnectorTypeUpdateValidation,
)
from mugen.core.plugin.ops_connector.contrib import contribute
from mugen.core.plugin.ops_connector.service.connector_call_log import (
    ConnectorCallLogService,
)
from mugen.core.plugin.ops_connector.service.connector_instance import (
    ConnectorInstanceService,
)
from mugen.core.plugin.ops_connector.service.connector_type import (
    ConnectorTypeService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsConnectorContribBinding(unittest.TestCase):
    """Tests ops_connector declarative registration and runtime materialization."""

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
            plugin_namespace="com.test.ops_connector",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        connector_types = registry.get_resource("OpsConnectorTypes")
        connector_instances = registry.get_resource("OpsConnectorInstances")
        connector_call_logs = registry.get_resource("OpsConnectorCallLogs")
        self.assertEqual(
            connector_types.crud.update_schema,
            ConnectorTypeUpdateValidation,
        )
        self.assertEqual(
            connector_instances.crud.update_schema,
            ConnectorInstanceUpdateValidation,
        )

        self.assertIn("ops_connector_type", fake_rsg.tables)
        self.assertIn("ops_connector_instance", fake_rsg.tables)
        self.assertIn("ops_connector_call_log", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(connector_types.service_key),
            ConnectorTypeService,
        )
        self.assertIsInstance(
            registry.get_edm_service(connector_instances.service_key),
            ConnectorInstanceService,
        )
        self.assertIsInstance(
            registry.get_edm_service(connector_call_logs.service_key),
            ConnectorCallLogService,
        )

        self.assertIn("test_connection", connector_instances.capabilities.actions)
        self.assertIn("invoke", connector_instances.capabilities.actions)

        test_connection_action = connector_instances.capabilities.actions[
            "test_connection"
        ]
        invoke_action = connector_instances.capabilities.actions["invoke"]
        self.assertEqual(
            test_connection_action["required_capabilities"],
            ["connector:invoke", "net:outbound", "secrets:read"],
        )
        self.assertEqual(
            invoke_action["required_capabilities"],
            ["connector:invoke", "net:outbound", "secrets:read"],
        )

        connector_type_edm = registry.schema.get_type("OPSCONNECTOR.ConnectorType")
        self.assertEqual(connector_type_edm.entity_set_name, "OpsConnectorTypes")

        connector_instance_edm = registry.schema.get_type(
            "OPSCONNECTOR.ConnectorInstance"
        )
        self.assertEqual(
            connector_instance_edm.entity_set_name,
            "OpsConnectorInstances",
        )

        connector_call_log_edm = registry.schema.get_type(
            "OPSCONNECTOR.ConnectorCallLog"
        )
        self.assertEqual(
            connector_call_log_edm.entity_set_name,
            "OpsConnectorCallLogs",
        )

    def test_connector_instance_update_validation_normalizes_and_rejects_invalid_values(
        self,
    ) -> None:
        validation = ConnectorInstanceUpdateValidation(
            connector_type_key=" stripe ",
            display_name=" Stripe Production ",
            config_json={"mode": "live"},
            secret_ref=" billing.stripe ",
            retry_policy_json={"max_attempts": 3},
            escalation_policy_key=" ops.escalate ",
        )
        self.assertEqual(validation.connector_type_key, "stripe")
        self.assertEqual(validation.display_name, "Stripe Production")
        self.assertEqual(validation.secret_ref, "billing.stripe")
        self.assertEqual(validation.config_json, {"mode": "live"})
        self.assertEqual(validation.retry_policy_json, {"max_attempts": 3})
        self.assertEqual(validation.escalation_policy_key, "ops.escalate")

        simple_validation = ConnectorInstanceUpdateValidation(
            display_name=" Backoffice connector "
        )
        self.assertEqual(simple_validation.display_name, "Backoffice connector")

        with self.assertRaisesRegex(
            ValueError,
            "At least one mutable ConnectorInstance field must be provided.",
        ):
            ConnectorInstanceUpdateValidation()

        with self.assertRaisesRegex(
            ValueError,
            "ConnectorTypeKey cannot be empty when provided.",
        ):
            ConnectorInstanceUpdateValidation(connector_type_key=" ")

        with self.assertRaisesRegex(
            ValueError,
            "DisplayName must be non-empty when provided.",
        ):
            ConnectorInstanceUpdateValidation(display_name=" ")

        with self.assertRaisesRegex(
            ValueError,
            "SecretRef must be non-empty when provided.",
        ):
            ConnectorInstanceUpdateValidation(secret_ref=" ")

        with self.assertRaisesRegex(
            ValueError,
            "ConfigJson must be an object when provided.",
        ):
            ConnectorInstanceUpdateValidation(config_json=[])

        with self.assertRaisesRegex(
            ValueError,
            "RetryPolicyJson must be an object when provided.",
        ):
            ConnectorInstanceUpdateValidation(retry_policy_json=[])
