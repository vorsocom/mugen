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
from mugen.core.plugin.acp.contrib import contribute
from mugen.core.plugin.acp.sdk.registry import AdminRegistry


class TestAcpContribRolePermissionLifecycle(unittest.TestCase):
    """Covers lifecycle action registration for role and permission resources."""

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


if __name__ == "__main__":
    unittest.main()
