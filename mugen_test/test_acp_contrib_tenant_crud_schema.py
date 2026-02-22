"""Focused tests for ACP tenant CRUD schema defaults."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest


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

    if "mugen.core.di" not in sys.modules:
        di_mod = ModuleType("mugen.core.di")
        di_mod.container = SimpleNamespace(
            config=SimpleNamespace(),
            logging_gateway=SimpleNamespace(debug=lambda *_: None),
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

from mugen.core.plugin.acp.contrib import contribute  # noqa: E402  pylint: disable=wrong-import-position
from mugen.core.plugin.acp.sdk.registry import AdminRegistry  # noqa: E402  pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.validation.generic import (  # noqa: E402  pylint: disable=wrong-import-position
    RowVersionValidation,
)
from mugen.core.plugin.acp.api.validation.tenant import (  # noqa: E402  pylint: disable=wrong-import-position
    TenantDomainCreateValidation,
    TenantDomainUpdateValidation,
    TenantInvitationCreateValidation,
    TenantInvitationUpdateValidation,
    TenantMembershipCreateValidation,
    TenantMembershipUpdateValidation,
)


class TestAcpContribTenantCrudSchema(unittest.TestCase):
    """Tests tenant CRUD schema registration for ACP generic endpoints."""

    def test_tenants_have_explicit_create_and_update_schema(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)

        contribute(
            registry,
            admin_namespace="com.test.acp",
            plugin_namespace="com.test.acp",
        )

        resource = registry.get_resource("Tenants")

        self.assertEqual(resource.crud.create_schema, ("Name", "Slug"))
        self.assertEqual(resource.crud.update_schema, ("Name", "Slug"))
        self.assertEqual(
            resource.capabilities.actions["deactivate"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            resource.capabilities.actions["reactivate"]["schema"],
            RowVersionValidation,
        )

        tenant_domain_resource = registry.get_resource("TenantDomains")
        self.assertEqual(
            tenant_domain_resource.crud.create_schema,
            TenantDomainCreateValidation,
        )
        self.assertEqual(
            tenant_domain_resource.crud.update_schema,
            TenantDomainUpdateValidation,
        )

        tenant_invitation_resource = registry.get_resource("TenantInvitations")
        self.assertEqual(
            tenant_invitation_resource.crud.create_schema,
            TenantInvitationCreateValidation,
        )
        self.assertEqual(
            tenant_invitation_resource.crud.update_schema,
            TenantInvitationUpdateValidation,
        )
        self.assertEqual(
            tenant_invitation_resource.capabilities.actions["resend"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            tenant_invitation_resource.capabilities.actions["revoke"]["schema"],
            RowVersionValidation,
        )

        tenant_membership_resource = registry.get_resource("TenantMemberships")
        self.assertEqual(
            tenant_membership_resource.crud.create_schema,
            TenantMembershipCreateValidation,
        )
        self.assertEqual(
            tenant_membership_resource.crud.update_schema,
            TenantMembershipUpdateValidation,
        )
        self.assertEqual(
            tenant_membership_resource.capabilities.actions["suspend"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            tenant_membership_resource.capabilities.actions["unsuspend"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            tenant_membership_resource.capabilities.actions["remove"]["schema"],
            RowVersionValidation,
        )


if __name__ == "__main__":
    unittest.main()
