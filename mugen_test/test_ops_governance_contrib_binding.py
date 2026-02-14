"""Unit tests for ops_governance ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_governance.contrib import contribute
from mugen.core.plugin.ops_governance.service.consent_record import ConsentRecordService
from mugen.core.plugin.ops_governance.service.data_handling_record import (
    DataHandlingRecordService,
)
from mugen.core.plugin.ops_governance.service.delegation_grant import (
    DelegationGrantService,
)
from mugen.core.plugin.ops_governance.service.policy_definition import (
    PolicyDefinitionService,
)
from mugen.core.plugin.ops_governance.service.policy_decision_log import (
    PolicyDecisionLogService,
)
from mugen.core.plugin.ops_governance.service.retention_policy import (
    RetentionPolicyService,
)


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsGovernanceContribBinding(unittest.TestCase):
    """Tests ops_governance declarative registration and runtime materialization."""

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
            plugin_namespace="com.test.ops_governance",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        consent = registry.get_resource("OpsConsentRecords")
        delegation = registry.get_resource("OpsDelegationGrants")
        policies = registry.get_resource("OpsPolicyDefinitions")
        decision_logs = registry.get_resource("OpsPolicyDecisionLogs")
        retentions = registry.get_resource("OpsRetentionPolicies")
        handling = registry.get_resource("OpsDataHandlingRecords")

        self.assertIn("ops_governance_consent_record", fake_rsg.tables)
        self.assertIn("ops_governance_delegation_grant", fake_rsg.tables)
        self.assertIn("ops_governance_policy_definition", fake_rsg.tables)
        self.assertIn("ops_governance_policy_decision_log", fake_rsg.tables)
        self.assertIn("ops_governance_retention_policy", fake_rsg.tables)
        self.assertIn("ops_governance_data_handling_record", fake_rsg.tables)

        self.assertIsInstance(
            registry.get_edm_service(consent.service_key),
            ConsentRecordService,
        )
        self.assertIsInstance(
            registry.get_edm_service(delegation.service_key),
            DelegationGrantService,
        )
        self.assertIsInstance(
            registry.get_edm_service(policies.service_key),
            PolicyDefinitionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(decision_logs.service_key),
            PolicyDecisionLogService,
        )
        self.assertIsInstance(
            registry.get_edm_service(retentions.service_key),
            RetentionPolicyService,
        )
        self.assertIsInstance(
            registry.get_edm_service(handling.service_key),
            DataHandlingRecordService,
        )

        self.assertIn("record_consent", consent.capabilities.actions)
        self.assertIn("withdraw_consent", consent.capabilities.actions)
        self.assertIn("grant_delegation", delegation.capabilities.actions)
        self.assertIn("revoke_delegation", delegation.capabilities.actions)
        self.assertIn("evaluate_policy", policies.capabilities.actions)
        self.assertIn("apply_retention_action", retentions.capabilities.actions)

        self.assertFalse(decision_logs.capabilities.allow_create)
        self.assertFalse(decision_logs.capabilities.allow_update)
        self.assertFalse(decision_logs.capabilities.allow_delete)

        policy_log_type = registry.schema.get_type("OPSGOVERNANCE.PolicyDecisionLog")
        self.assertEqual(policy_log_type.entity_set_name, "OpsPolicyDecisionLogs")
