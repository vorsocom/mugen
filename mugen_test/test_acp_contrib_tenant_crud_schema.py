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

from mugen.core.plugin.acp.contrib import contribute  # noqa: E402
from mugen.core.plugin.acp.sdk.registry import AdminRegistry  # noqa: E402
from mugen.core.plugin.acp.api.validation.generic import (  # noqa: E402
    # pylint: disable=wrong-import-position
    RowVersionValidation,
)
from mugen.core.plugin.acp.api.validation.tenant import (  # noqa: E402
    # pylint: disable=wrong-import-position
    TenantCreateValidation,
    TenantDomainCreateValidation,
    TenantDomainUpdateValidation,
    TenantInvitationCreateValidation,
    TenantInvitationUpdateValidation,
    TenantMembershipCreateValidation,
    TenantMembershipUpdateValidation,
    TenantUpdateValidation,
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

        self.assertEqual(resource.crud.create_schema, TenantCreateValidation)
        self.assertEqual(resource.crud.update_schema, TenantUpdateValidation)
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

    def test_tenant_validators_enforce_non_empty_text_and_nonempty_patch(
        self,
    ) -> None:
        validation = TenantCreateValidation(
            name=" Example Tenant ",
            slug=" example-tenant ",
        )
        self.assertEqual(validation.name, "Example Tenant")
        self.assertEqual(validation.slug, "example-tenant")

        with self.assertRaisesRegex(ValueError, "Name must be non-empty."):
            TenantCreateValidation(name=" ", slug="example")

        with self.assertRaisesRegex(ValueError, "Slug must be non-empty."):
            TenantCreateValidation(name="Example", slug=" ")

        update_validation = TenantUpdateValidation(name=" Updated Tenant ")
        self.assertEqual(update_validation.name, "Updated Tenant")

        null_update = TenantUpdateValidation(slug=None)
        self.assertIsNone(null_update.slug)

        with self.assertRaisesRegex(
            ValueError,
            "At least one mutable field must be provided.",
        ):
            TenantUpdateValidation()

        with self.assertRaisesRegex(
            ValueError,
            "Name must be non-empty when provided.",
        ):
            TenantUpdateValidation(name=" ")

    def test_related_tenant_validators_trim_domain_and_require_patch_fields(
        self,
    ) -> None:
        domain_create = TenantDomainCreateValidation(
            tenant_id="11111111-1111-1111-1111-111111111111",
            domain=" example.com ",
        )
        self.assertEqual(domain_create.domain, "example.com")

        with self.assertRaisesRegex(ValueError, "Domain must be non-empty."):
            TenantDomainCreateValidation(
                tenant_id="11111111-1111-1111-1111-111111111111",
                domain=" ",
            )

        domain_update = TenantDomainUpdateValidation(domain=" app.example.com ")
        self.assertEqual(domain_update.domain, "app.example.com")

        passthrough_update = TenantDomainUpdateValidation(is_primary=True, domain=None)
        self.assertIsNone(passthrough_update.domain)
        self.assertTrue(passthrough_update.is_primary)

        with self.assertRaisesRegex(
            ValueError,
            "At least one mutable field must be provided.",
        ):
            TenantDomainUpdateValidation()

        with self.assertRaisesRegex(ValueError, "Domain must be non-empty."):
            TenantDomainUpdateValidation(domain=" ")

        with self.assertRaisesRegex(
            ValueError,
            "At least one mutable field must be provided.",
        ):
            TenantInvitationUpdateValidation()

        invitation_update = TenantInvitationUpdateValidation(
            email="tenant@example.com"
        )
        self.assertEqual(invitation_update.email, "tenant@example.com")

        with self.assertRaisesRegex(
            ValueError,
            "At least one mutable field must be provided.",
        ):
            TenantMembershipUpdateValidation()

        membership_update = TenantMembershipUpdateValidation(status="active")
        self.assertEqual(membership_update.status, "active")


if __name__ == "__main__":
    unittest.main()
