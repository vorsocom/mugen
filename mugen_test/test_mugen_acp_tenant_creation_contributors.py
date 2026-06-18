"""Tests for ACP tenant creation contributors and template materialization."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import sys
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy.exc import IntegrityError


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
        di_mod.EXT_SERVICE_ADMIN_REGISTRY = "admin_registry"
        di_mod.container = SimpleNamespace(
            config=SimpleNamespace(),
            logging_gateway=SimpleNamespace(),
            get_required_ext_service=lambda *_: None,
        )
        sys.modules["mugen.core.di"] = di_mod
        setattr(sys.modules["mugen.core"], "di", di_mod)


_bootstrap_namespace_packages()

# noqa: E402
# pylint: disable=wrong-import-position
from mugen.core.plugin.acp.contract.sdk import tenant_lifecycle as lifecycle_mod
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultTenantTemplateGrant,
    TenantRoleTemplateDef,
)
from mugen.core.plugin.acp.contract.sdk.seed import AdminSeedManifest
from mugen.core.plugin.acp.sdk import tenant_materialization as materialization_mod
from mugen.core.plugin.acp.sdk.tenant_materialization import (
    materialize_tenant_role_templates,
)
from mugen.core.plugin.acp.service import tenant as tenant_mod
from mugen.core.plugin.acp.service.tenant import TenantService


def _empty_manifest() -> AdminSeedManifest:
    return AdminSeedManifest(
        permission_objects=[],
        permission_types=[],
        global_roles=[],
        tenant_role_templates=[],
        default_global_grants=[],
        default_tenant_grants=[],
        system_flags=[],
    )


class _FakeCrudService:
    """Small in-memory async CRUD service for materializer tests."""

    def __init__(self, records: list[SimpleNamespace] | None = None) -> None:
        self.records = list(records or [])

    async def get(
        self,
        where: dict[str, Any],
        *,
        columns: tuple[str, ...] | None = None,  # noqa: ARG002
    ) -> SimpleNamespace | None:
        for record in self.records:
            if all(getattr(record, key, None) == value for key, value in where.items()):
                return record
        return None

    async def create(self, values: dict[str, Any]) -> SimpleNamespace:
        record = SimpleNamespace(id=uuid.uuid4(), **values)
        self.records.append(record)
        return record

    async def update(
        self,
        where: dict[str, Any],
        changes: dict[str, Any],
    ) -> SimpleNamespace | None:
        record = await self.get(where)
        if record is None:
            return None
        for key, value in changes.items():
            setattr(record, key, value)
        return record


class _ConflictAfterMissService(_FakeCrudService):
    """Simulates a concurrent insert after the first lookup misses."""

    def __init__(self, record: SimpleNamespace) -> None:
        super().__init__([record])
        self._first_get = True

    async def get(
        self,
        where: dict[str, Any],
        *,
        columns: tuple[str, ...] | None = None,
    ) -> SimpleNamespace | None:
        if self._first_get:
            self._first_get = False
            return None
        return await super().get(where, columns=columns)

    async def create(self, values: dict[str, Any]) -> SimpleNamespace:  # noqa: ARG002
        raise IntegrityError("insert", {}, Exception("duplicate"))


class _AlwaysConflictService(_FakeCrudService):
    """Simulates an insert conflict where the conflicting row cannot be re-read."""

    async def create(self, values: dict[str, Any]) -> SimpleNamespace:  # noqa: ARG002
        raise IntegrityError("insert", {}, Exception("duplicate"))


class _UpdateMissService(_FakeCrudService):
    """Simulates an update that affects no rows."""

    async def update(
        self,
        where: dict[str, Any],  # noqa: ARG002
        changes: dict[str, Any],  # noqa: ARG002
    ) -> SimpleNamespace | None:
        return None


class _NoIdCreateService(_FakeCrudService):
    """Creates a record without an id for defensive branch coverage."""

    async def create(self, values: dict[str, Any]) -> SimpleNamespace:
        record = SimpleNamespace(id=None, **values)
        self.records.append(record)
        return record


class _FakeRegistry:
    """Registry facade that resolves fake services by EDM type name."""

    def __init__(
        self,
        *,
        manifest: AdminSeedManifest,
        services: dict[str, _FakeCrudService],
    ) -> None:
        self._manifest = manifest
        self._services = services

    def build_seed_manifest(self) -> AdminSeedManifest:
        return self._manifest

    def get_resource_by_type(self, edm_type_name: str) -> SimpleNamespace:
        return SimpleNamespace(service_key=edm_type_name)

    def get_edm_service(self, service_key: str) -> _FakeCrudService:
        return self._services[service_key]


class TestMugenAcpTenantCreationContributors(unittest.IsolatedAsyncioTestCase):
    """Covers tenant-created extension hooks and template materialization."""

    def setUp(self) -> None:
        lifecycle_mod._TENANT_LIFECYCLE_CONTRIBUTORS.clear()

    def tearDown(self) -> None:
        lifecycle_mod._TENANT_LIFECYCLE_CONTRIBUTORS.clear()

    def test_default_registry_provider_reads_di_container(self) -> None:
        registry = SimpleNamespace()
        container = SimpleNamespace(
            get_required_ext_service=lambda key: registry
            if key == "admin_registry"
            else None
        )

        with patch.object(
            tenant_mod.di,
            "EXT_SERVICE_ADMIN_REGISTRY",
            "admin_registry",
            create=True,
        ):
            with patch.object(tenant_mod.di, "container", container):
                self.assertIs(tenant_mod._registry_provider(), registry)

    def test_contributor_registration_is_ordered_and_duplicate_safe(self) -> None:
        first = SimpleNamespace(tenant_created=AsyncMock())
        second = SimpleNamespace(tenant_created=AsyncMock())

        lifecycle_mod.register_tenant_lifecycle_contributor(first)
        lifecycle_mod.register_tenant_lifecycle_contributor(first)
        lifecycle_mod.register_tenant_lifecycle_contributor(second)

        self.assertEqual(
            lifecycle_mod.tenant_lifecycle_contributors(),
            (first, second),
        )

    async def test_tenant_create_invokes_materializer_and_contributor(self) -> None:
        tenant_id = uuid.uuid4()
        registry = SimpleNamespace()
        contributor = SimpleNamespace(tenant_created=AsyncMock())
        lifecycle_mod.register_tenant_lifecycle_contributor(contributor)
        rsg = SimpleNamespace(
            insert_one=AsyncMock(
                return_value={
                    "id": tenant_id,
                    "name": "Acme",
                    "slug": "acme",
                    "status": "active",
                }
            )
        )
        svc = TenantService(
            table="admin_tenant",
            rsg=rsg,
            registry_provider=lambda: registry,
        )

        with patch.object(
            tenant_mod,
            "materialize_tenant_role_templates",
            new_callable=AsyncMock,
        ) as materialize:
            tenant = await svc.create({"name": "Acme", "slug": "acme"})

        self.assertEqual(tenant.id, tenant_id)
        rsg.insert_one.assert_awaited_once_with(
            "admin_tenant",
            {"name": "Acme", "slug": "acme"},
        )
        materialize.assert_awaited_once_with(
            tenant_id=tenant_id,
            registry=registry,
        )
        contributor.tenant_created.assert_awaited_once_with(
            tenant=tenant,
            registry=registry,
        )

    async def test_tenant_create_propagates_contributor_failure(self) -> None:
        tenant_id = uuid.uuid4()
        registry = SimpleNamespace()
        contributor = SimpleNamespace(
            tenant_created=AsyncMock(side_effect=RuntimeError("provisioning failed"))
        )
        lifecycle_mod.register_tenant_lifecycle_contributor(contributor)
        rsg = SimpleNamespace(
            insert_one=AsyncMock(
                return_value={
                    "id": tenant_id,
                    "name": "Acme",
                    "slug": "acme",
                    "status": "active",
                }
            )
        )
        svc = TenantService(
            table="admin_tenant",
            rsg=rsg,
            registry_provider=lambda: registry,
        )

        with patch.object(
            tenant_mod,
            "materialize_tenant_role_templates",
            new_callable=AsyncMock,
        ):
            with self.assertRaisesRegex(RuntimeError, "provisioning failed"):
                await svc.create({"name": "Acme", "slug": "acme"})

    async def test_tenant_create_still_works_without_contributors(self) -> None:
        tenant_id = uuid.uuid4()
        registry = _FakeRegistry(
            manifest=_empty_manifest(),
            services={},
        )
        rsg = SimpleNamespace(
            insert_one=AsyncMock(
                return_value={
                    "id": tenant_id,
                    "name": "Acme",
                    "slug": "acme",
                    "status": "active",
                }
            )
        )
        svc = TenantService(
            table="admin_tenant",
            rsg=rsg,
            registry_provider=lambda: registry,
        )

        tenant = await svc.create({"name": "Acme", "slug": "acme"})

        self.assertEqual(tenant.id, tenant_id)

    async def test_tenant_create_requires_registry(self) -> None:
        rsg = SimpleNamespace(
            insert_one=AsyncMock(
                return_value={
                    "id": uuid.uuid4(),
                    "name": "Acme",
                    "slug": "acme",
                    "status": "active",
                }
            )
        )
        svc = TenantService(
            table="admin_tenant",
            rsg=rsg,
            registry_provider=lambda: None,
        )

        with self.assertRaisesRegex(RuntimeError, "ACP registry is required"):
            await svc.create({"name": "Acme", "slug": "acme"})

    async def test_tenant_create_requires_created_tenant_id(self) -> None:
        rsg = SimpleNamespace(
            insert_one=AsyncMock(
                return_value={
                    "id": None,
                    "name": "Acme",
                    "slug": "acme",
                    "status": "active",
                }
            )
        )
        svc = TenantService(
            table="admin_tenant",
            rsg=rsg,
            registry_provider=lambda: _FakeRegistry(
                manifest=_empty_manifest(),
                services={},
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "Created tenant has no id"):
            await svc.create({"name": "Acme", "slug": "acme"})

    async def test_materialization_creates_roles_and_grants_idempotently(self) -> None:
        tenant_id = uuid.uuid4()
        permission_object_id = uuid.uuid4()
        permission_type_id = uuid.uuid4()
        manifest = _empty_manifest()
        manifest.tenant_role_templates.append(
            TenantRoleTemplateDef("redcell_wargame", "operator", "Operator")
        )
        manifest.default_tenant_grants.append(
            DefaultTenantTemplateGrant(
                tenant_role_template="redcell_wargame:operator",
                permission_object="redcell_wargame:scenario",
                permission_type="acp:read",
                permitted=True,
            )
        )
        role_svc = _FakeCrudService()
        entry_svc = _FakeCrudService()
        registry = _FakeRegistry(
            manifest=manifest,
            services={
                "ACP.Role": role_svc,
                "ACP.PermissionEntry": entry_svc,
                "ACP.PermissionObject": _FakeCrudService(
                    [
                        SimpleNamespace(
                            id=permission_object_id,
                            namespace="redcell_wargame",
                            name="scenario",
                        )
                    ]
                ),
                "ACP.PermissionType": _FakeCrudService(
                    [
                        SimpleNamespace(
                            id=permission_type_id,
                            namespace="acp",
                            name="read",
                        )
                    ]
                ),
            },
        )

        await materialize_tenant_role_templates(
            tenant_id=tenant_id,
            registry=registry,
        )
        await materialize_tenant_role_templates(
            tenant_id=tenant_id,
            registry=registry,
        )

        self.assertEqual(len(role_svc.records), 1)
        role = role_svc.records[0]
        self.assertEqual(role.tenant_id, tenant_id)
        self.assertEqual(role.namespace, "redcell_wargame")
        self.assertEqual(role.name, "operator")
        self.assertEqual(role.display_name, "Operator")

        self.assertEqual(len(entry_svc.records), 1)
        entry = entry_svc.records[0]
        self.assertEqual(entry.tenant_id, tenant_id)
        self.assertEqual(entry.role_id, role.id)
        self.assertEqual(entry.permission_object_id, permission_object_id)
        self.assertEqual(entry.permission_type_id, permission_type_id)
        self.assertTrue(entry.permitted)

    async def test_materialization_updates_templates_without_touching_memberships(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        role_id = uuid.uuid4()
        permission_object_id = uuid.uuid4()
        permission_type_id = uuid.uuid4()
        membership = SimpleNamespace(id=uuid.uuid4())
        role = SimpleNamespace(
            id=role_id,
            tenant_id=tenant_id,
            namespace="redcell_wargame",
            name="operator",
            display_name="Old Operator",
            role_memberships=[membership],
        )
        entry = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            role_id=role_id,
            permission_object_id=permission_object_id,
            permission_type_id=permission_type_id,
            permitted=False,
        )
        manifest = _empty_manifest()
        manifest.tenant_role_templates.append(
            TenantRoleTemplateDef("redcell_wargame", "operator", "Operator")
        )
        manifest.default_tenant_grants.append(
            DefaultTenantTemplateGrant(
                tenant_role_template="redcell_wargame:operator",
                permission_object="redcell_wargame:scenario",
                permission_type="acp:read",
                permitted=True,
            )
        )
        role_svc = _FakeCrudService([role])
        entry_svc = _FakeCrudService([entry])
        registry = _FakeRegistry(
            manifest=manifest,
            services={
                "ACP.Role": role_svc,
                "ACP.PermissionEntry": entry_svc,
                "ACP.PermissionObject": _FakeCrudService(
                    [
                        SimpleNamespace(
                            id=permission_object_id,
                            namespace="redcell_wargame",
                            name="scenario",
                        )
                    ]
                ),
                "ACP.PermissionType": _FakeCrudService(
                    [
                        SimpleNamespace(
                            id=permission_type_id,
                            namespace="acp",
                            name="read",
                        )
                    ]
                ),
            },
        )

        await materialize_tenant_role_templates(
            tenant_id=tenant_id,
            registry=registry,
        )

        self.assertEqual(len(role_svc.records), 1)
        self.assertEqual(role.display_name, "Operator")
        self.assertEqual(role.role_memberships, [membership])
        self.assertEqual(len(entry_svc.records), 1)
        self.assertTrue(entry.permitted)

    async def test_materialization_handles_templates_without_grants(self) -> None:
        tenant_id = uuid.uuid4()
        manifest = _empty_manifest()
        manifest.tenant_role_templates.append(
            TenantRoleTemplateDef("redcell_wargame", "viewer", "Viewer")
        )
        role_svc = _FakeCrudService()
        registry = _FakeRegistry(
            manifest=manifest,
            services={"ACP.Role": role_svc},
        )

        await materialize_tenant_role_templates(
            tenant_id=tenant_id,
            registry=registry,
        )

        self.assertEqual(len(role_svc.records), 1)
        self.assertEqual(role_svc.records[0].name, "viewer")

    async def test_materialization_reuses_permission_lookup_cache(self) -> None:
        tenant_id = uuid.uuid4()
        permission_object_id = uuid.uuid4()
        permission_type_id = uuid.uuid4()
        manifest = _empty_manifest()
        manifest.tenant_role_templates.extend(
            [
                TenantRoleTemplateDef("redcell_wargame", "operator", "Operator"),
                TenantRoleTemplateDef("redcell_wargame", "viewer", "Viewer"),
            ]
        )
        manifest.default_tenant_grants.extend(
            [
                DefaultTenantTemplateGrant(
                    tenant_role_template="redcell_wargame:operator",
                    permission_object="redcell_wargame:scenario",
                    permission_type="acp:read",
                    permitted=True,
                ),
                DefaultTenantTemplateGrant(
                    tenant_role_template="redcell_wargame:viewer",
                    permission_object="redcell_wargame:scenario",
                    permission_type="acp:read",
                    permitted=True,
                ),
            ]
        )
        role_svc = _FakeCrudService()
        entry_svc = _FakeCrudService()
        registry = _FakeRegistry(
            manifest=manifest,
            services={
                "ACP.Role": role_svc,
                "ACP.PermissionEntry": entry_svc,
                "ACP.PermissionObject": _FakeCrudService(
                    [
                        SimpleNamespace(
                            id=permission_object_id,
                            namespace="redcell_wargame",
                            name="scenario",
                        )
                    ]
                ),
                "ACP.PermissionType": _FakeCrudService(
                    [
                        SimpleNamespace(
                            id=permission_type_id,
                            namespace="acp",
                            name="read",
                        )
                    ]
                ),
            },
        )

        await materialize_tenant_role_templates(
            tenant_id=tenant_id,
            registry=registry,
        )

        self.assertEqual(len(role_svc.records), 2)
        self.assertEqual(len(entry_svc.records), 2)

    async def test_materialization_error_paths(self) -> None:
        tenant_id = uuid.uuid4()
        permission_object_id = uuid.uuid4()
        permission_type_id = uuid.uuid4()

        with self.assertRaisesRegex(ValueError, "expected"):
            materialization_mod._norm_key("missing-colon")
        with self.assertRaisesRegex(ValueError, "empty namespace"):
            materialization_mod._norm_key(":missing-namespace")

        role = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            namespace="redcell_wargame",
            name="operator",
            display_name="Old",
        )
        refreshed = await materialization_mod._update_role_display_name(
            _UpdateMissService([role]),
            where={"tenant_id": tenant_id},
            role=role,
            display_name="New",
        )
        self.assertIs(refreshed, role)
        with self.assertRaisesRegex(RuntimeError, "Tenant role disappeared"):
            await materialization_mod._update_role_display_name(
                _UpdateMissService(),
                where={"tenant_id": tenant_id},
                role=role,
                display_name="New",
            )

        raced_role = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            namespace="redcell_wargame",
            name="operator",
            display_name="Operator",
        )
        ensured = await materialization_mod._ensure_role(
            _ConflictAfterMissService(raced_role),
            tenant_id=tenant_id,
            template=TenantRoleTemplateDef(
                "redcell_wargame",
                "operator",
                "Operator",
            ),
        )
        self.assertIs(ensured, raced_role)
        with self.assertRaises(IntegrityError):
            await materialization_mod._ensure_role(
                _AlwaysConflictService(),
                tenant_id=tenant_id,
                template=TenantRoleTemplateDef(
                    "redcell_wargame",
                    "operator",
                    "Operator",
                ),
            )

        entry = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            role_id=role.id,
            permission_object_id=permission_object_id,
            permission_type_id=permission_type_id,
            permitted=False,
        )
        refreshed_entry = await materialization_mod._update_permission_entry(
            _UpdateMissService([entry]),
            where={"tenant_id": tenant_id},
            entry=entry,
            permitted=True,
        )
        self.assertIs(refreshed_entry, entry)
        with self.assertRaisesRegex(RuntimeError, "permission entry disappeared"):
            await materialization_mod._update_permission_entry(
                _UpdateMissService(),
                where={"tenant_id": tenant_id},
                entry=entry,
                permitted=True,
            )

        raced_entry = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            role_id=role.id,
            permission_object_id=permission_object_id,
            permission_type_id=permission_type_id,
            permitted=True,
        )
        ensured_entry = await materialization_mod._ensure_permission_entry(
            _ConflictAfterMissService(raced_entry),
            tenant_id=tenant_id,
            role_id=role.id,
            permission_object_id=permission_object_id,
            permission_type_id=permission_type_id,
            grant=DefaultTenantTemplateGrant(
                tenant_role_template="redcell_wargame:operator",
                permission_object="redcell_wargame:scenario",
                permission_type="acp:read",
                permitted=True,
            ),
        )
        self.assertIs(ensured_entry, raced_entry)
        with self.assertRaises(IntegrityError):
            await materialization_mod._ensure_permission_entry(
                _AlwaysConflictService(),
                tenant_id=tenant_id,
                role_id=role.id,
                permission_object_id=permission_object_id,
                permission_type_id=permission_type_id,
                grant=DefaultTenantTemplateGrant(
                    tenant_role_template="redcell_wargame:operator",
                    permission_object="redcell_wargame:scenario",
                    permission_type="acp:read",
                    permitted=True,
                ),
            )

    async def test_materialization_public_error_paths(self) -> None:
        tenant_id = uuid.uuid4()
        permission_object_id = uuid.uuid4()
        permission_type_id = uuid.uuid4()

        missing_object_manifest = _empty_manifest()
        missing_object_manifest.tenant_role_templates.append(
            TenantRoleTemplateDef("redcell_wargame", "operator", "Operator")
        )
        missing_object_manifest.default_tenant_grants.append(
            DefaultTenantTemplateGrant(
                tenant_role_template="redcell_wargame:operator",
                permission_object="redcell_wargame:scenario",
                permission_type="acp:read",
                permitted=True,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "unknown permission object"):
            await materialize_tenant_role_templates(
                tenant_id=tenant_id,
                registry=_FakeRegistry(
                    manifest=missing_object_manifest,
                    services={
                        "ACP.Role": _FakeCrudService(),
                        "ACP.PermissionEntry": _FakeCrudService(),
                        "ACP.PermissionObject": _FakeCrudService(),
                        "ACP.PermissionType": _FakeCrudService(
                            [
                                SimpleNamespace(
                                    id=permission_type_id,
                                    namespace="acp",
                                    name="read",
                                )
                            ]
                        ),
                    },
                ),
            )

        missing_type_manifest = _empty_manifest()
        missing_type_manifest.tenant_role_templates.append(
            TenantRoleTemplateDef("redcell_wargame", "operator", "Operator")
        )
        missing_type_manifest.default_tenant_grants.append(
            DefaultTenantTemplateGrant(
                tenant_role_template="redcell_wargame:operator",
                permission_object="redcell_wargame:scenario",
                permission_type="acp:read",
                permitted=True,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "unknown permission type"):
            await materialize_tenant_role_templates(
                tenant_id=tenant_id,
                registry=_FakeRegistry(
                    manifest=missing_type_manifest,
                    services={
                        "ACP.Role": _FakeCrudService(),
                        "ACP.PermissionEntry": _FakeCrudService(),
                        "ACP.PermissionObject": _FakeCrudService(
                            [
                                SimpleNamespace(
                                    id=permission_object_id,
                                    namespace="redcell_wargame",
                                    name="scenario",
                                )
                            ]
                        ),
                        "ACP.PermissionType": _FakeCrudService(),
                    },
                ),
            )

        no_role_id_manifest = _empty_manifest()
        no_role_id_manifest.tenant_role_templates.append(
            TenantRoleTemplateDef("redcell_wargame", "operator", "Operator")
        )
        with self.assertRaisesRegex(RuntimeError, "has no id"):
            await materialize_tenant_role_templates(
                tenant_id=tenant_id,
                registry=_FakeRegistry(
                    manifest=no_role_id_manifest,
                    services={"ACP.Role": _NoIdCreateService()},
                ),
            )

        undeclared_manifest = _empty_manifest()
        undeclared_manifest.default_tenant_grants.append(
            DefaultTenantTemplateGrant(
                tenant_role_template="redcell_wargame:operator",
                permission_object="redcell_wargame:scenario",
                permission_type="acp:read",
                permitted=True,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "undeclared tenant role template"):
            await materialize_tenant_role_templates(
                tenant_id=tenant_id,
                registry=_FakeRegistry(
                    manifest=undeclared_manifest,
                    services={
                        "ACP.Role": _FakeCrudService(),
                        "ACP.PermissionEntry": _FakeCrudService(),
                        "ACP.PermissionObject": _FakeCrudService(),
                        "ACP.PermissionType": _FakeCrudService(),
                    },
                ),
            )
