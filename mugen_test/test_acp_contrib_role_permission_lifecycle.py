"""Focused tests for ACP role and permission lifecycle action wiring."""

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

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.api.validation.generic import (
    RowVersionValidation,
)
from mugen.core.plugin.acp.constants import (  # noqa: E402
    GLOBAL_ROLE_HANDOFF_OPERATOR,
    GLOBAL_ROLE_WEB_USER,
)
from mugen.core.plugin.acp.contrib import contribute
from mugen.core.plugin.acp.sdk.registry import AdminRegistry


class TestAcpContribRolePermissionLifecycle(unittest.TestCase):
    """Covers lifecycle action registration for role and permission resources."""

    def test_contribute_registers_least_privilege_global_roles(self) -> None:
        """Contributor should seed least privilege global roles."""
        admin_namespace = "com.test.acp"
        registry = AdminRegistry(strict_permission_decls=True)

        contribute(
            registry,
            admin_namespace=admin_namespace,
            plugin_namespace=admin_namespace,
        )

        manifest = registry.build_seed_manifest()
        roles = {role.key: role.display_name for role in manifest.global_roles}
        self.assertEqual(
            roles[f"{admin_namespace}:{GLOBAL_ROLE_WEB_USER}"],
            "Web User",
        )
        self.assertEqual(
            roles[f"{admin_namespace}:{GLOBAL_ROLE_HANDOFF_OPERATOR}"],
            "Handoff Operator",
        )

    def test_resources_register_lifecycle_actions(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)

        contribute(
            registry,
            admin_namespace="com.test.acp",
            plugin_namespace="com.test.acp",
        )

        role_resource = registry.get_resource("Roles")
        self.assertEqual(
            role_resource.capabilities.actions["deprecate"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            role_resource.capabilities.actions["reactivate"]["schema"],
            RowVersionValidation,
        )

        permission_object_resource = registry.get_resource("PermissionObjects")
        self.assertFalse(permission_object_resource.capabilities.allow_delete)
        self.assertEqual(
            permission_object_resource.capabilities.actions["deprecate"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            permission_object_resource.capabilities.actions["reactivate"]["schema"],
            RowVersionValidation,
        )

        permission_type_resource = registry.get_resource("PermissionTypes")
        self.assertFalse(permission_type_resource.capabilities.allow_delete)
        self.assertEqual(
            permission_type_resource.capabilities.actions["deprecate"]["schema"],
            RowVersionValidation,
        )
        self.assertEqual(
            permission_type_resource.capabilities.actions["reactivate"]["schema"],
            RowVersionValidation,
        )

    def test_global_roles_and_memberships_register_search_fields(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)

        contribute(
            registry,
            admin_namespace="com.test.acp",
            plugin_namespace="com.test.acp",
        )

        global_roles = registry.get_resource("GlobalRoles")
        self.assertEqual(
            global_roles.behavior.search_fields,
            ("Namespace", "Name", "DisplayName"),
        )

        global_role_memberships = registry.get_resource("GlobalRoleMemberships")
        self.assertEqual(
            global_role_memberships.behavior.search_fields,
            (
                "User/Username",
                "User/LoginEmail",
                "GlobalRole/Namespace",
                "GlobalRole/Name",
                "GlobalRole/DisplayName",
            ),
        )


if __name__ == "__main__":
    unittest.main()
