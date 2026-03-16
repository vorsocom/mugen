"""Unit tests for mugen.core.plugin.acp.service.authorization."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.acp.service import authorization as auth_mod
from mugen.core.plugin.acp.service.authorization import AuthorizationService


def _row_with_id(value: uuid.UUID):
    return SimpleNamespace(id=value)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            modules=SimpleNamespace(
                extensions=[
                    SimpleNamespace(
                        type="fw",
                        token="core.fw.acp",
                        namespace="com.vorso",
                    )
                ]
            )
        )
    )


class TestMugenAcpServiceAuthorization(unittest.IsolatedAsyncioTestCase):
    """Covers permission lookup caching and has_permission decision branches."""

    def _new_service(self):
        services = {
            "ACP.GlobalPermissionEntry": SimpleNamespace(
                list=AsyncMock(return_value=[])
            ),
            "ACP.GlobalRoleMembership": SimpleNamespace(
                get_role_memberships_by_user=AsyncMock(return_value=[])
            ),
            "ACP.PermissionEntry": SimpleNamespace(list=AsyncMock(return_value=[])),
            "ACP.PermissionObject": SimpleNamespace(get=AsyncMock(return_value=None)),
            "ACP.PermissionType": SimpleNamespace(get=AsyncMock(return_value=None)),
            "ACP.RoleMembership": SimpleNamespace(
                get_role_memberships_by_user=AsyncMock(return_value=[])
            ),
            "ACP.User": SimpleNamespace(get_expanded=AsyncMock(return_value=None)),
        }

        registry = SimpleNamespace(
            get_edm_service=lambda key: services[key.split(":", 1)[1]]
        )
        svc = AuthorizationService(
            config_provider=_config,
            registry_provider=lambda: registry,
        )
        return svc, services

    def test_provider_helpers(self) -> None:
        fake_config = SimpleNamespace()
        fake_registry = Mock()
        with patch.object(
            auth_mod.di,
            "container",
            new=SimpleNamespace(
                config=fake_config,
                get_required_ext_service=lambda _name: fake_registry,
            ),
        ):
            self.assertIs(
                auth_mod._config_provider(), fake_config
            )  # pylint: disable=protected-access
            self.assertIs(
                auth_mod._registry_provider(), fake_registry
            )  # pylint: disable=protected-access

    async def test_permission_id_caching_helpers(self) -> None:
        svc, services = self._new_service()
        obj_id = uuid.uuid4()
        typ_id = uuid.uuid4()
        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(obj_id)
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(typ_id)
        )

        resolved_obj = await svc._get_perm_obj_id(
            "com.vorso", "users"
        )  # pylint: disable=protected-access
        resolved_obj_cached = (
            await svc._get_perm_obj_id(  # pylint: disable=protected-access
                "com.vorso", "users"
            )
        )
        self.assertEqual(resolved_obj, obj_id)
        self.assertEqual(resolved_obj_cached, obj_id)
        services["ACP.PermissionObject"].get.assert_awaited_once()

        resolved_typ = await svc._get_perm_type_id(
            "com.vorso", "read"
        )  # pylint: disable=protected-access
        resolved_typ_cached = (
            await svc._get_perm_type_id(  # pylint: disable=protected-access
                "com.vorso", "read"
            )
        )
        self.assertEqual(resolved_typ, typ_id)
        self.assertEqual(resolved_typ_cached, typ_id)
        services["ACP.PermissionType"].get.assert_awaited_once()

        services["ACP.PermissionObject"].get = AsyncMock(return_value=None)
        missing_obj = await svc._get_perm_obj_id(
            "com.vorso", "missing"
        )  # pylint: disable=protected-access
        self.assertIsNone(missing_obj)

    async def test_has_permission_short_circuits_and_global_admin(self) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Missing permission object/type rows -> immediate deny.
        denied_missing = await svc.has_permission(
            user_id=user_id,
            permission_object=":users",
            permission_type=":read",
            tenant_id=tenant_id,
            allow_global_admin=False,
        )
        self.assertFalse(denied_missing)

        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.User"].get_expanded = AsyncMock(
            return_value=SimpleNamespace(
                global_roles=[
                    SimpleNamespace(namespace="com.vorso", name="administrator"),
                ]
            )
        )

        allowed_global_admin = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
            allow_global_admin=True,
        )
        self.assertTrue(allowed_global_admin)

    async def test_has_permission_global_and_tenant_resolution(self) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        global_role_id = uuid.uuid4()
        role_id = uuid.uuid4()

        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.GlobalRoleMembership"].get_role_memberships_by_user = AsyncMock(
            side_effect=[
                [SimpleNamespace(global_role_id=global_role_id)],
                [SimpleNamespace(global_role_id=global_role_id)],
                [],
                [],
                [],
                [],
            ]
        )
        services["ACP.GlobalPermissionEntry"].list = AsyncMock(
            side_effect=[
                [SimpleNamespace(permitted=False)],
                [SimpleNamespace(permitted=True)],
            ]
        )
        services["ACP.RoleMembership"].get_role_memberships_by_user = AsyncMock(
            side_effect=[
                [],
                [SimpleNamespace(role_id=role_id)],
                [SimpleNamespace(role_id=role_id)],
            ]
        )
        services["ACP.PermissionEntry"].list = AsyncMock(
            side_effect=[
                [SimpleNamespace(permitted=False)],
                [SimpleNamespace(permitted=True)],
            ]
        )

        denied_global = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
        )
        self.assertFalse(denied_global)

        allowed_global = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
        )
        self.assertTrue(allowed_global)

        denied_no_tenant = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=None,
        )
        self.assertFalse(denied_no_tenant)

        denied_no_roles = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
        )
        self.assertFalse(denied_no_roles)

        denied_tenant = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
        )
        self.assertFalse(denied_tenant)

        allowed_tenant = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
        )
        self.assertTrue(allowed_tenant)

    async def test_has_permission_global_admin_fallthrough_paths(self) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()
        global_role_id = uuid.uuid4()

        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.User"].get_expanded = AsyncMock(
            side_effect=[
                None,
                SimpleNamespace(
                    global_roles=[SimpleNamespace(namespace="com.vorso", name="viewer")]
                ),
            ]
        )
        services["ACP.GlobalRoleMembership"].get_role_memberships_by_user = AsyncMock(
            side_effect=[[], [SimpleNamespace(global_role_id=global_role_id)]]
        )
        services["ACP.GlobalPermissionEntry"].list = AsyncMock(
            return_value=[SimpleNamespace(permitted=None)]
        )

        denied_missing_user = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=None,
            allow_global_admin=True,
        )
        self.assertFalse(denied_missing_user)

        denied_non_admin_with_neutral_global_entry = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="com.vorso:read",
            tenant_id=None,
            allow_global_admin=True,
        )
        self.assertFalse(denied_non_admin_with_neutral_global_entry)

    async def test_has_permission_rejects_malformed_permission_keys(self) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        malformed_object = await svc.has_permission(
            user_id=user_id,
            permission_object="users",
            permission_type="com.vorso:read",
            tenant_id=tenant_id,
        )
        self.assertFalse(malformed_object)

        malformed_type = await svc.has_permission(
            user_id=user_id,
            permission_object="com.vorso:users",
            permission_type="read",
            tenant_id=tenant_id,
        )
        self.assertFalse(malformed_type)

        services["ACP.PermissionObject"].get.assert_not_awaited()
        services["ACP.PermissionType"].get.assert_not_awaited()
