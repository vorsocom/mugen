"""Unit tests for ops_vpn ACP contribution and runtime binding."""

import unittest

from mugen.core.plugin.acp.contract.sdk.permission import (
    GlobalRoleDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.sdk.runtime_binder import AdminRuntimeBinder
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.plugin.ops_vpn.contrib import contribute
from mugen.core.plugin.ops_vpn.service.scorecard_policy import ScorecardPolicyService
from mugen.core.plugin.ops_vpn.service.taxonomy_domain import TaxonomyDomainService
from mugen.core.plugin.ops_vpn.service.vendor import VendorService
from mugen.core.plugin.ops_vpn.service.verification_criterion import (
    VerificationCriterionService,
)
from mugen.core.plugin.ops_vpn.service.vendor_scorecard import VendorScorecardService


class _FakeRsg:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.tables = {}

    def register_tables(self, tables) -> None:
        self.tables = dict(tables)


class TestOpsVpnContribBinding(unittest.TestCase):
    """Tests ops_vpn declarative registration and runtime materialization."""

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
            plugin_namespace="com.test.ops_vpn",
        )

        fake_rsg = _FakeRsg()
        AdminRuntimeBinder(registry=registry, rsg=fake_rsg).bind_all()
        registry.freeze()

        taxonomy_domains = registry.get_resource("OpsVpnTaxonomyDomains")
        vendors = registry.get_resource("OpsVpnVendors")
        scorecards = registry.get_resource("OpsVpnVendorScorecards")
        criteria = registry.get_resource("OpsVpnVerificationCriteria")
        policies = registry.get_resource("OpsVpnScorecardPolicies")

        self.assertIn("ops_vpn_taxonomy_domain", fake_rsg.tables)
        self.assertIn("ops_vpn_taxonomy_category", fake_rsg.tables)
        self.assertIn("ops_vpn_taxonomy_subcategory", fake_rsg.tables)
        self.assertIn("ops_vpn_vendor", fake_rsg.tables)
        self.assertIn("ops_vpn_verification_criterion", fake_rsg.tables)
        self.assertIn("ops_vpn_scorecard_policy", fake_rsg.tables)
        self.assertIn("ops_vpn_vendor_scorecard", fake_rsg.tables)
        self.assertIn(taxonomy_domains.service_key, registry.edm_services)
        self.assertIn(vendors.service_key, registry.edm_services)
        self.assertIn(scorecards.service_key, registry.edm_services)
        self.assertIn(criteria.service_key, registry.edm_services)
        self.assertIn(policies.service_key, registry.edm_services)

        self.assertIsInstance(
            registry.get_edm_service(taxonomy_domains.service_key),
            TaxonomyDomainService,
        )
        self.assertIsInstance(
            registry.get_edm_service(vendors.service_key),
            VendorService,
        )
        self.assertIsInstance(
            registry.get_edm_service(scorecards.service_key),
            VendorScorecardService,
        )
        self.assertIsInstance(
            registry.get_edm_service(criteria.service_key),
            VerificationCriterionService,
        )
        self.assertIsInstance(
            registry.get_edm_service(policies.service_key),
            ScorecardPolicyService,
        )

        taxonomy_domain_type = registry.schema.get_type("OPSVPN.TaxonomyDomain")
        self.assertEqual(
            taxonomy_domain_type.entity_set_name,
            "OpsVpnTaxonomyDomains",
        )
        vendor_type = registry.schema.get_type("OPSVPN.Vendor")
        self.assertEqual(vendor_type.entity_set_name, "OpsVpnVendors")
