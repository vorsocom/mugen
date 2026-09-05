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
            "ACP.Tenant": SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(status="active", deleted_at=None)
                )
            ),
            "ACP.TenantMembership": SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(status="active"))
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

    def _granted_service(self, *, global_grant: bool = False):
        svc, services = self._new_service()
        services["ACP.PermissionObject"].get.return_value = _row_with_id(uuid.uuid4())
        services["ACP.PermissionType"].get.return_value = _row_with_id(uuid.uuid4())
        services["ACP.RoleMembership"].get_role_memberships_by_user.return_value = [
            SimpleNamespace(role_id=uuid.uuid4())
        ]
        services["ACP.PermissionEntry"].list.return_value = [
            SimpleNamespace(permitted=True)
        ]
        if global_grant:
            services[
                "ACP.GlobalRoleMembership"
            ].get_role_memberships_by_user.return_value = [
                SimpleNamespace(global_role_id=uuid.uuid4())
            ]
            services["ACP.GlobalPermissionEntry"].list.return_value = [
                SimpleNamespace(permitted=True)
            ]
        return svc, services

    async def test_membership_state_gates_tenant_and_global_grants(self) -> None:
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        for global_grant in (False, True):
            for status in (None, "invited", "suspended", "unknown", "active"):
                with self.subTest(global_grant=global_grant, status=status):
                    svc, services = self._granted_service(global_grant=global_grant)
                    services["ACP.User"].get_expanded.return_value = SimpleNamespace(
                        global_roles=[
                            SimpleNamespace(
                                namespace="unrelated.namespace", name="administrator"
                            )
                        ]
                    )
                    services["ACP.TenantMembership"].get.return_value = (
                        None if status is None else SimpleNamespace(status=status)
                    )

                    permitted = await svc.has_permission(
                        user_id=user_id,
                        permission_object=":users",
                        permission_type=":read",
                        tenant_id=tenant_id,
                        allow_global_admin=True,
                    )

                    self.assertEqual(permitted, status == "active")
                    services["ACP.Tenant"].get.assert_awaited_once_with(
                        {"id": tenant_id}
                    )
                    services["ACP.TenantMembership"].get.assert_awaited_once_with(
                        {"tenant_id": tenant_id, "user_id": user_id}
                    )
                    if status != "active":
                        services["ACP.PermissionEntry"].list.assert_not_awaited()
                        services["ACP.GlobalPermissionEntry"].list.assert_not_awaited()

    async def test_inactive_tenants_deny_even_global_administrators(self) -> None:
        for is_admin in (False, True):
            for tenant in (
                None,
                SimpleNamespace(status="suspended", deleted_at=None),
                SimpleNamespace(status=None, deleted_at=None),
                SimpleNamespace(status="active", deleted_at="deleted"),
            ):
                with self.subTest(is_admin=is_admin, tenant=tenant):
                    svc, services = self._granted_service(global_grant=True)
                    services["ACP.Tenant"].get.return_value = tenant
                    if is_admin:
                        services["ACP.User"].get_expanded.return_value = (
                            SimpleNamespace(
                                global_roles=[
                                    SimpleNamespace(
                                        namespace="com.vorso", name="administrator"
                                    )
                                ]
                            )
                        )

                    self.assertFalse(
                        await svc.has_permission(
                            user_id=uuid.uuid4(),
                            permission_object=":users",
                            permission_type=":read",
                            tenant_id=uuid.uuid4(),
                            allow_global_admin=True,
                        )
                    )
                    services["ACP.TenantMembership"].get.assert_not_awaited()
                    services["ACP.GlobalPermissionEntry"].list.assert_not_awaited()

    async def test_admin_membership_exemption_preserves_grant_policy(self) -> None:
        for override in (False, True):
            for grant in (False, True):
                with self.subTest(override=override, grant=grant):
                    svc, services = self._granted_service(global_grant=True)
                    services["ACP.User"].get_expanded.return_value = SimpleNamespace(
                        global_roles=[
                            SimpleNamespace(namespace="com.vorso", name="administrator")
                        ]
                    )
                    services["ACP.TenantMembership"].get.return_value = None
                    services["ACP.GlobalPermissionEntry"].list.return_value = [
                        SimpleNamespace(permitted=grant)
                    ]

                    permitted = await svc.has_permission(
                        user_id=uuid.uuid4(),
                        permission_object=":users",
                        permission_type=":read",
                        tenant_id=uuid.uuid4(),
                        allow_global_admin=override,
                    )

                    self.assertEqual(permitted, override or grant)
                    services["ACP.TenantMembership"].get.assert_not_awaited()

    async def test_warm_permission_cache_respects_membership_and_tenant_changes(
        self,
    ) -> None:
        svc, services = self._granted_service()
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        tenant = services["ACP.Tenant"].get.return_value
        membership = services["ACP.TenantMembership"].get.return_value

        for tenant_status, membership_status, expected in (
            ("active", "active", True),
            ("active", "suspended", False),
            ("active", "active", True),
            ("suspended", "active", False),
            ("active", "active", True),
        ):
            tenant.status = tenant_status
            membership.status = membership_status
            self.assertEqual(
                await svc.has_permission(
                    user_id=user_id,
                    permission_object=":users",
                    permission_type=":read",
                    tenant_id=tenant_id,
                ),
                expected,
            )

        services["ACP.PermissionObject"].get.assert_awaited_once()
        services["ACP.PermissionType"].get.assert_awaited_once()
        self.assertEqual(services["ACP.Tenant"].get.await_count, 5)

    async def test_any_tenant_access_excludes_suspended_memberships(self) -> None:
        svc, services = self._granted_service()
        revoked_tenant_id = uuid.uuid4()
        active_tenant_id = uuid.uuid4()
        memberships = {
            revoked_tenant_id: SimpleNamespace(status="suspended"),
            active_tenant_id: SimpleNamespace(status="active"),
        }
        services["ACP.TenantMembership"].get.side_effect = (
            lambda where: memberships[where["tenant_id"]]
        )
        services["ACP.RoleMembership"].get_role_memberships_by_user.return_value = [
            SimpleNamespace(tenant_id=revoked_tenant_id, role_id=uuid.uuid4()),
            SimpleNamespace(tenant_id=active_tenant_id, role_id=uuid.uuid4()),
        ]

        for expected in (True, False):
            self.assertEqual(
                await svc.has_permission_for_any_tenant(
                    user_id=uuid.uuid4(),
                    permission_object=":users",
                    permission_type=":read",
                ),
                expected,
            )
            memberships[active_tenant_id].status = "suspended"

        self.assertEqual(services["ACP.PermissionEntry"].list.await_count, 1)

    async def test_has_permission_for_any_tenant_uses_tenant_role_grant(
        self,
    ) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        role_id = uuid.uuid4()

        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.User"].get_expanded = AsyncMock(
            return_value=SimpleNamespace(global_roles=[])
        )
        services["ACP.RoleMembership"].get_role_memberships_by_user = AsyncMock(
            side_effect=[
                [
                    SimpleNamespace(
                        tenant_id=tenant_id,
                        role_id=role_id,
                    )
                ],
                [SimpleNamespace(role_id=role_id)],
            ]
        )
        services["ACP.PermissionEntry"].list = AsyncMock(
            return_value=[SimpleNamespace(permitted=True)]
        )

        allowed = await svc.has_permission_for_any_tenant(
            user_id=user_id,
            permission_object=(
                "com.vorsocomputing.mugen.human_handoff:operator"
            ),
            permission_type=(
                "com.vorsocomputing.mugen.human_handoff:operator"
            ),
            allow_global_admin=True,
        )

        self.assertTrue(allowed)
        self.assertEqual(
            services["ACP.RoleMembership"]
            .get_role_memberships_by_user.await_args_list[0]
            .args[0],
            {"user_id": user_id},
        )
        self.assertEqual(
            services["ACP.RoleMembership"]
            .get_role_memberships_by_user.await_args_list[1]
            .args[0],
            {"tenant_id": tenant_id, "user_id": user_id},
        )

    async def test_has_permission_for_any_tenant_honors_global_admin(self) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()

        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.User"].get_expanded = AsyncMock(
            return_value=SimpleNamespace(
                global_roles=[
                    SimpleNamespace(namespace="com.vorso", name="administrator")
                ]
            )
        )

        allowed = await svc.has_permission_for_any_tenant(
            user_id=user_id,
            permission_object=(
                "com.vorsocomputing.mugen.human_handoff:operator"
            ),
            permission_type=(
                "com.vorsocomputing.mugen.human_handoff:operator"
            ),
            allow_global_admin=True,
        )

        self.assertTrue(allowed)
        services["ACP.RoleMembership"].get_role_memberships_by_user.assert_not_awaited()

    async def test_has_permission_for_any_tenant_denies_without_effective_grant(
        self,
    ) -> None:
        svc, services = self._new_service()
        user_id = uuid.uuid4()
        tenant_id_one = uuid.uuid4()
        tenant_id_two = uuid.uuid4()

        services["ACP.PermissionObject"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.PermissionType"].get = AsyncMock(
            return_value=_row_with_id(uuid.uuid4())
        )
        services["ACP.User"].get_expanded = AsyncMock(
            return_value=SimpleNamespace(global_roles=[])
        )
        services["ACP.RoleMembership"].get_role_memberships_by_user = AsyncMock(
            side_effect=[
                [
                    SimpleNamespace(tenant_id=None, role_id=uuid.uuid4()),
                    SimpleNamespace(tenant_id=tenant_id_one, role_id=uuid.uuid4()),
                    SimpleNamespace(tenant_id=tenant_id_one, role_id=uuid.uuid4()),
                    SimpleNamespace(tenant_id=tenant_id_two, role_id=uuid.uuid4()),
                ],
                [SimpleNamespace(role_id=uuid.uuid4())],
                [SimpleNamespace(role_id=uuid.uuid4())],
            ]
        )
        services["ACP.PermissionEntry"].list = AsyncMock(return_value=[])

        allowed = await svc.has_permission_for_any_tenant(
            user_id=user_id,
            permission_object=(
                "com.vorsocomputing.mugen.human_handoff:operator"
            ),
            permission_type=(
                "com.vorsocomputing.mugen.human_handoff:operator"
            ),
            allow_global_admin=True,
        )

        self.assertFalse(allowed)
        self.assertEqual(
            [
                call.args[0]
                for call in (
                    services["ACP.RoleMembership"]
                    .get_role_memberships_by_user
                    .await_args_list
                )
            ],
            [
                {"user_id": user_id},
                {"tenant_id": tenant_id_one, "user_id": user_id},
                {"tenant_id": tenant_id_two, "user_id": user_id},
            ],
        )
