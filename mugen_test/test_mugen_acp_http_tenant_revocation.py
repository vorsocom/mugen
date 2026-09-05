"""HTTP regressions for ACP tenant membership and tenant revocation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from quart import Quart

from mugen.core import di
from mugen.core.plugin.acp.api import action as action_mod
from mugen.core.plugin.acp.api import crud as crud_mod
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminCapabilities,
    AdminPermissions,
    AdminResource,
)
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.service.authorization import AuthorizationService
from mugen.core.plugin.acp.service.tenant_membership import TenantMembershipService
from mugen.core.plugin.channel_orchestration.api import human_handoff_events
from mugen.core.utility.rgql.model import (
    EdmProperty,
    EdmType,
    EntitySet,
    TypeRef,
)


class TestAcpHttpTenantRevocation(unittest.IsolatedAsyncioTestCase):
    """Exercise real HTTP guards, queries, and suspension with mocked storage."""

    async def asyncSetUp(self) -> None:
        self.namespace = "com.test.acp"
        self.user_id = uuid.uuid4()
        self.manager_id = uuid.uuid4()
        self.admin_id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()
        self.other_tenant_id = uuid.uuid4()
        self.unrelated_tenant_id = uuid.uuid4()
        self.role_ids = {self.user_id: uuid.uuid4(), self.manager_id: uuid.uuid4()}
        self.global_role_id = uuid.uuid4()
        self.users = {
            user_id: SimpleNamespace(
                id=user_id,
                deleted_at=None,
                locked_at=None,
                token_version=1,
                global_roles=[],
            )
            for user_id in (self.user_id, self.manager_id, self.admin_id)
        }
        self.users[self.admin_id].global_roles = [
            SimpleNamespace(namespace=self.namespace, name="administrator")
        ]
        self.tenants = {
            tenant_id: SimpleNamespace(id=tenant_id, status="active", deleted_at=None)
            for tenant_id in (
                self.tenant_id,
                self.other_tenant_id,
                self.unrelated_tenant_id,
            )
        }
        self.memberships = [
            {
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "status": "active",
                "row_version": 1,
            }
            for tenant_id, user_id in (
                (self.tenant_id, self.user_id),
                (self.other_tenant_id, self.user_id),
                (self.tenant_id, self.manager_id),
            )
        ]
        self.membership_id = self.memberships[0]["id"]
        self.other_membership_id = self.memberships[1]["id"]
        self.role_memberships = [
            SimpleNamespace(
                tenant_id=row["tenant_id"],
                user_id=row["user_id"],
                role_id=self.role_ids[row["user_id"]],
            )
            for row in self.memberships
        ]

        def get_one(_table, where, **_):
            return next(
                (
                    dict(row)
                    for row in self.memberships
                    if all(row.get(key) == value for key, value in where.items())
                ),
                None,
            )

        def update_one(_table, *, where, changes):
            row = next(
                row
                for row in self.memberships
                if all(row.get(key) == value for key, value in where.items())
            )
            row.update(changes)
            row["row_version"] += 1
            return dict(row)

        def find_many(_table, *, filter_groups, **_):
            return [
                dict(row)
                for row in self.memberships
                if any(
                    all(row.get(key) == value for key, value in group.where.items())
                    for group in filter_groups
                )
            ]

        self.storage = SimpleNamespace(
            get_one=AsyncMock(side_effect=get_one),
            update_one=AsyncMock(side_effect=update_one),
            find_many=AsyncMock(side_effect=find_many),
        )
        self.membership_svc = TenantMembershipService(
            table="tenant_memberships",
            rsg=self.storage,
        )
        self.global_memberships = SimpleNamespace(
            get_role_memberships_by_user=AsyncMock(
                side_effect=lambda where: (
                    [SimpleNamespace(global_role_id=self.global_role_id)]
                    if where["user_id"] == self.admin_id
                    else []
                )
            )
        )
        self.role_membership_svc = SimpleNamespace(
            get_role_memberships_by_user=AsyncMock(
                side_effect=lambda where: [
                    row
                    for row in self.role_memberships
                    if all(getattr(row, key) == value for key, value in where.items())
                ]
            )
        )
        self.permission_entries = SimpleNamespace(
            list=AsyncMock(return_value=[SimpleNamespace(permitted=True)])
        )
        self.global_entries = SimpleNamespace(
            list=AsyncMock(return_value=[SimpleNamespace(permitted=True)])
        )
        services = {
            "ACP.Tenant": SimpleNamespace(
                get=AsyncMock(side_effect=lambda where: self.tenants.get(where["id"]))
            ),
            "ACP.TenantMembership": self.membership_svc,
            "ACP.User": SimpleNamespace(
                get=AsyncMock(side_effect=lambda where: self.users.get(where["id"])),
                get_expanded=AsyncMock(
                    side_effect=lambda where: self.users.get(where["id"])
                )
            ),
            "ACP.GlobalRoleMembership": self.global_memberships,
            "ACP.GlobalPermissionEntry": self.global_entries,
            "ACP.RoleMembership": self.role_membership_svc,
            "ACP.PermissionEntry": self.permission_entries,
            "ACP.PermissionObject": SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
            ),
            "ACP.PermissionType": SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
            ),
        }
        registry = AdminRegistry()
        for type_name, service in services.items():
            registry.register_edm_service(f"{self.namespace}:{type_name}", service)

        resource = AdminResource(
            namespace=self.namespace,
            entity_set="TenantMemberships",
            edm_type_name="ACP.TenantMembership",
            perm_obj=f"{self.namespace}:tenant_membership",
            service_key=f"{self.namespace}:ACP.TenantMembership",
            permissions=AdminPermissions(
                permission_object=f"{self.namespace}:tenant_membership",
                **{
                    op: f"{self.namespace}:{op}"
                    for op in ("read", "create", "update", "delete", "manage")
                },
            ),
            capabilities=AdminCapabilities(
                actions={
                    action: {
                        "perm": f"{self.namespace}:manage",
                        "schema": RowVersionValidation,
                    }
                    for action in ("suspend", "unsuspend")
                }
            ),
        )
        registry.register_resource(resource)
        membership_type = EdmType(
            name="ACP.TenantMembership",
            kind="entity",
            properties={
                name: EdmProperty(name=name, type=TypeRef(type_name), nullable=False)
                for name, type_name in (
                    ("Id", "Edm.Guid"),
                    ("TenantId", "Edm.Guid"),
                    ("UserId", "Edm.Guid"),
                    ("Status", "Edm.String"),
                    ("RowVersion", "Edm.Int64"),
                )
            },
        )
        registry.register_edm_schema(
            types={membership_type.name: membership_type},
            entity_sets={
                "TenantMemberships": EntitySet(
                    name="TenantMemberships", type=TypeRef(membership_type.name)
                )
            },
        )
        config = SimpleNamespace(
            acp=SimpleNamespace(),
            mugen=SimpleNamespace(
                modules=SimpleNamespace(
                    extensions=[
                        SimpleNamespace(
                            type="fw", token="core.fw.acp", namespace=self.namespace
                        )
                    ]
                )
            ),
        )
        self.authorization = AuthorizationService(
            config_provider=lambda: config,
            registry_provider=lambda: registry,
        )
        self.jwt_svc = SimpleNamespace(
            verify=Mock(
                side_effect=lambda token, **_: {"sub": token, "token_version": 1}
            )
        )
        self.extension_services = {
            di.EXT_SERVICE_ADMIN_REGISTRY: registry,
            di.EXT_SERVICE_ADMIN_SVC_AUTH: self.authorization,
            di.EXT_SERVICE_ADMIN_SVC_JWT: self.jwt_svc,
        }
        container = SimpleNamespace(
            config=config,
            logging_gateway=Mock(),
            get_required_ext_service=self.extension_services.__getitem__,
        )
        self.enterContext(patch.object(di, "container", new=container))
        self.app = Quart("acp-http-tenant-revocation")
        self.app.testing = True
        base = "/api/core/acp/v1/tenants/<tenant_id>/<entity_set>"
        self.app.add_url_rule(
            base,
            view_func=crud_mod.get_entities_tenant,
            defaults={"entity_id": None},
        )
        self.app.add_url_rule(
            f"{base}/<entity_id>",
            view_func=crud_mod.get_entities_tenant,
        )
        self.app.add_url_rule(
            f"{base}/<entity_id>/$action/<action>",
            view_func=action_mod.dispatch_entity_action_tenant,
            methods=["POST"],
        )
        self.client = self.app.test_client()
        self.user_headers = {"Authorization": f"Bearer {self.user_id}"}
        self.manager_headers = {"Authorization": f"Bearer {self.manager_id}"}
        self.admin_headers = {"Authorization": f"Bearer {self.admin_id}"}

    def _collection_path(self, tenant_id: uuid.UUID) -> str:
        return f"/api/core/acp/v1/tenants/{tenant_id}/TenantMemberships"

    async def _transition(self, action: str, row_version: int):
        return await self.client.post(
            f"{self._collection_path(self.tenant_id)}/{self.membership_id}"
            f"/$action/{action}",
            headers=self.manager_headers,
            json={"RowVersion": row_version},
        )

    async def test_suspension_revokes_existing_token_and_preserves_other_tenant(self):
        for tenant_id in (self.tenant_id, self.other_tenant_id):
            response = await self.client.get(
                self._collection_path(tenant_id), headers=self.user_headers
            )
            self.assertEqual(response.status_code, 200)

        before_roles = list(self.role_memberships)
        suspended = await self._transition("suspend", 1)
        self.assertEqual(suspended.status_code, 204)
        self.assertEqual(self.memberships[0]["status"], "suspended")
        self.assertEqual(self.role_memberships, before_roles)
        self.assertEqual(self.users[self.user_id].token_version, 1)
        self.assertTrue(self.authorization._perm_obj_id_cache)
        self.assertTrue(self.authorization._perm_type_id_cache)

        self.storage.find_many.reset_mock()
        self.storage.update_one.reset_mock()
        path = self._collection_path(self.tenant_id)
        for denied_path in (path, f"{path}/{self.membership_id}"):
            response = await self.client.get(denied_path, headers=self.user_headers)
            self.assertEqual(response.status_code, 403)
        self.storage.find_many.assert_not_awaited()

        response = await self.client.post(
            f"{path}/{self.membership_id}/$action/unsuspend",
            headers=self.user_headers,
            json={"RowVersion": 2},
        )
        self.assertEqual(response.status_code, 403)
        self.storage.update_one.assert_not_awaited()

        response = await self.client.get(
            self._collection_path(self.other_tenant_id), headers=self.user_headers
        )
        self.assertEqual(response.status_code, 200)
        payload = await response.get_json()
        self.assertEqual(len(payload["value"]), 1)
        self.assertEqual(payload["value"][0]["Id"], str(self.other_membership_id))
        self.assertEqual(payload["value"][0]["TenantId"], str(self.other_tenant_id))

        response = await self.client.get(
            self._collection_path(self.unrelated_tenant_id), headers=self.user_headers
        )
        self.assertEqual(response.status_code, 403)

        restored = await self._transition("unsuspend", 2)
        self.assertEqual(restored.status_code, 204)
        response = await self.client.get(path, headers=self.user_headers)
        self.assertEqual(response.status_code, 200)

    async def test_suspension_also_revokes_ordinary_global_permission_grants(self):
        self.global_memberships.get_role_memberships_by_user.side_effect = None
        self.global_memberships.get_role_memberships_by_user.return_value = [
            SimpleNamespace(global_role_id=self.global_role_id)
        ]
        self.permission_entries.list.return_value = []
        path = self._collection_path(self.tenant_id)
        response = await self.client.get(path, headers=self.user_headers)
        self.assertEqual(response.status_code, 200)
        self.global_entries.list.assert_awaited()

        suspended = await self._transition("suspend", 1)
        self.assertEqual(suspended.status_code, 204)
        response = await self.client.get(path, headers=self.user_headers)
        self.assertEqual(response.status_code, 403)
        response = await self.client.get(
            self._collection_path(self.other_tenant_id), headers=self.user_headers
        )
        self.assertEqual(response.status_code, 200)

    async def test_global_admin_without_membership_requires_active_tenant(self):
        path = self._collection_path(self.tenant_id)
        response = await self.client.get(path, headers=self.admin_headers)
        self.assertEqual(response.status_code, 200)
        self.global_entries.list.assert_awaited()

        self.tenants[self.tenant_id].status = "suspended"
        for headers in (self.user_headers, self.admin_headers):
            response = await self.client.get(path, headers=headers)
            self.assertEqual(response.status_code, 403)
            response = await self.client.get(
                self._collection_path(self.other_tenant_id), headers=headers
            )
            self.assertEqual(response.status_code, 200)

    async def test_open_handoff_stream_revokes_after_http_membership_suspension(self):
        release_next_event = asyncio.Event()
        closed_tenants = set()

        async def stream(tenant_id):
            try:
                yield "data: before suspension\n\n"
                await release_next_event.wait()
                yield "data: after suspension\n\n"
            finally:
                closed_tenants.add(tenant_id)

        self.extension_services[di.EXT_SERVICE_HUMAN_HANDOFF] = SimpleNamespace(
            stream_handoff_events=AsyncMock(
                side_effect=lambda **kwargs: stream(kwargs["tenant_id"])
            )
        )
        self.app.add_url_rule(
            "/api/core/acp/v1/tenants/<tenant_id>/HumanHandoffEvents/stream",
            view_func=human_handoff_events.human_handoff_events_stream,
        )
        path = "/api/core/acp/v1/tenants/{}/HumanHandoffEvents/stream"
        async with asyncio.timeout(5):
            async with (
                self.client.request(
                    path.format(self.tenant_id),
                    method="GET",
                    headers=self.user_headers,
                ) as revoked_stream,
                self.client.request(
                    path.format(self.other_tenant_id),
                    method="GET",
                    headers=self.user_headers,
                ) as other_stream,
            ):
                for connection in (revoked_stream, other_stream):
                    self.assertEqual(
                        await connection.receive(), b"data: before suspension\n\n"
                    )
                    self.assertEqual(connection.status_code, 200)

                suspended = await self._transition("suspend", 1)
                self.assertEqual(suspended.status_code, 204)
                self.assertEqual(self.memberships[0]["status"], "suspended")
                release_next_event.set()

                self.assertEqual(await revoked_stream.receive(), b"")
                self.assertEqual(
                    await other_stream.receive(), b"data: after suspension\n\n"
                )
                self.assertEqual(await other_stream.receive(), b"")

        self.assertEqual(closed_tenants, {self.tenant_id, self.other_tenant_id})
        response = await self.client.get(
            path.format(self.tenant_id), headers=self.user_headers
        )
        self.assertEqual(response.status_code, 403)
