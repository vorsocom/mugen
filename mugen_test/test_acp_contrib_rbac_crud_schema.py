"""Focused tests for ACP RBAC CRUD schema defaults."""

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

from mugen.core.plugin.acp.api.validation.rbac import (  # noqa: E402  pylint: disable=wrong-import-position
    GlobalPermissionEntryCreateValidation,
    GlobalPermissionEntryUpdateValidation,
    GlobalRoleCreateValidation,
    GlobalRoleUpdateValidation,
    PermissionEntryCreateValidation,
    PermissionEntryUpdateValidation,
    PermissionObjectCreateValidation,
    PermissionTypeCreateValidation,
    RoleCreateValidation,
    RoleUpdateValidation,
)
from mugen.core.plugin.acp.contrib import contribute  # noqa: E402  pylint: disable=wrong-import-position
from mugen.core.plugin.acp.sdk.registry import (  # noqa: E402  pylint: disable=wrong-import-position
    AdminRegistry,
)


class TestAcpContribRbacCrudSchema(unittest.TestCase):
    """Tests RBAC CRUD schema registration for ACP generic endpoints."""

    def test_rbac_resources_have_typed_crud_schemas_and_mutability_flags(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)

        contribute(
            registry,
            admin_namespace="com.test.acp",
            plugin_namespace="com.test.acp",
        )

        global_roles = registry.get_resource("GlobalRoles")
        self.assertEqual(global_roles.crud.create_schema, GlobalRoleCreateValidation)
        self.assertEqual(global_roles.crud.update_schema, GlobalRoleUpdateValidation)

        roles = registry.get_resource("Roles")
        self.assertEqual(roles.crud.create_schema, RoleCreateValidation)
        self.assertEqual(roles.crud.update_schema, RoleUpdateValidation)

        global_permission_entries = registry.get_resource("GlobalPermissionEntries")
        self.assertEqual(
            global_permission_entries.crud.create_schema,
            GlobalPermissionEntryCreateValidation,
        )
        self.assertEqual(
            global_permission_entries.crud.update_schema,
            GlobalPermissionEntryUpdateValidation,
        )

        permission_entries = registry.get_resource("PermissionEntries")
        self.assertEqual(
            permission_entries.crud.create_schema,
            PermissionEntryCreateValidation,
        )
        self.assertEqual(
            permission_entries.crud.update_schema,
            PermissionEntryUpdateValidation,
        )

        permission_objects = registry.get_resource("PermissionObjects")
        self.assertFalse(permission_objects.capabilities.allow_update)
        self.assertEqual(
            permission_objects.crud.create_schema,
            PermissionObjectCreateValidation,
        )

        permission_types = registry.get_resource("PermissionTypes")
        self.assertFalse(permission_types.capabilities.allow_update)
        self.assertEqual(
            permission_types.crud.create_schema,
            PermissionTypeCreateValidation,
        )


if __name__ == "__main__":
    unittest.main()
