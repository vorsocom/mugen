"""Unit tests for mugen.core.plugin.web.contrib."""

import unittest

from mugen.core.plugin.acp.constants import (
    GLOBAL_ROLE_ADMINISTRATOR,
    GLOBAL_ROLE_WEB_USER,
)
from mugen.core.plugin.acp.contract.sdk.permission import GlobalRoleDef
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.web.auth import WEB_PLATFORM_ACCESS_PERMISSION
from mugen.core.plugin.web.contrib import contribute


class TestMuGenWebContrib(unittest.TestCase):
    """Test ACP contribution for the web framework plugin."""

    def test_contribute_registers_web_access_permission_seed_metadata(self) -> None:
        admin_namespace = "com.vorsocomputing.mugen.acp"
        registry = AdminRegistry(strict_permission_decls=True)
        for name, display_name in (
            (GLOBAL_ROLE_ADMINISTRATOR, "Administrator"),
            (GLOBAL_ROLE_WEB_USER, "Web User"),
        ):
            registry.register_global_role(
                GlobalRoleDef(
                    namespace=admin_namespace,
                    name=name,
                    display_name=display_name,
                )
            )

        contribute(
            registry,
            admin_namespace=admin_namespace,
            plugin_namespace="com.vorsocomputing.mugen.web",
        )
        registry.freeze(seeding=True)
        manifest = registry.build_seed_manifest()

        self.assertIn(
            WEB_PLATFORM_ACCESS_PERMISSION,
            [obj.key for obj in manifest.permission_objects],
        )
        self.assertIn(
            WEB_PLATFORM_ACCESS_PERMISSION,
            [typ.key for typ in manifest.permission_types],
        )
        self.assertTrue(
            any(
                grant.global_role == f"{admin_namespace}:{GLOBAL_ROLE_ADMINISTRATOR}"
                and grant.permission_object == WEB_PLATFORM_ACCESS_PERMISSION
                and grant.permission_type == WEB_PLATFORM_ACCESS_PERMISSION
                and grant.permitted is True
                for grant in manifest.default_global_grants
            )
        )
        self.assertTrue(
            any(
                grant.global_role == f"{admin_namespace}:{GLOBAL_ROLE_WEB_USER}"
                and grant.permission_object == WEB_PLATFORM_ACCESS_PERMISSION
                and grant.permission_type == WEB_PLATFORM_ACCESS_PERMISSION
                and grant.permitted is True
                for grant in manifest.default_global_grants
            )
        )
