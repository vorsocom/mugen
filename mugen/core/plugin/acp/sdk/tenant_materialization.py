"""Tenant role template materialization helpers."""

from __future__ import annotations

__all__ = ["materialize_tenant_role_templates"]

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultTenantTemplateGrant,
    TenantRoleTemplateDef,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.domain import (
    PermissionEntryDE,
    PermissionObjectDE,
    PermissionTypeDE,
    RoleDE,
)

_EDM_PERMISSION_ENTRY = "ACP.PermissionEntry"
_EDM_PERMISSION_OBJECT = "ACP.PermissionObject"
_EDM_PERMISSION_TYPE = "ACP.PermissionType"
_EDM_ROLE = "ACP.Role"


def _norm_token(value: str) -> str:
    return value.strip().lower()


def _norm_key(value: str) -> str:
    key = value.strip()
    if ":" not in key:
        raise ValueError(f"Invalid key {value!r}: expected '<namespace>:<name>'")
    namespace, name = key.split(":", 1)
    norm_namespace = _norm_token(namespace)
    norm_name = _norm_token(name)
    if not norm_namespace or not norm_name:
        raise ValueError(f"Invalid key {value!r}: empty namespace or name")
    return f"{norm_namespace}:{norm_name}"


def _split_key(value: str) -> tuple[str, str]:
    key = _norm_key(value)
    namespace, name = key.split(":", 1)
    return namespace, name


def _service_for(registry: IAdminRegistry, edm_type_name: str) -> Any:
    resource = registry.get_resource_by_type(edm_type_name)
    return registry.get_edm_service(resource.service_key)


async def _update_role_display_name(
    role_svc: Any,
    *,
    where: dict[str, Any],
    role: RoleDE,
    display_name: str,
) -> RoleDE:
    if role.display_name == display_name:
        return role

    updated = await role_svc.update(where, {"display_name": display_name})
    if updated is not None:
        return updated

    refreshed = await role_svc.get(where)
    if refreshed is None:
        raise RuntimeError("Tenant role disappeared during template materialization.")
    return refreshed


async def _ensure_role(
    role_svc: Any,
    *,
    tenant_id: UUID,
    template: TenantRoleTemplateDef,
) -> RoleDE:
    where = {
        "tenant_id": tenant_id,
        "namespace": template.namespace,
        "name": template.name,
    }
    existing = await role_svc.get(where)
    if existing is not None:
        return await _update_role_display_name(
            role_svc,
            where=where,
            role=existing,
            display_name=template.display_name,
        )

    try:
        return await role_svc.create(
            {
                "tenant_id": tenant_id,
                "namespace": template.namespace,
                "name": template.name,
                "display_name": template.display_name,
                "status": "active",
            }
        )
    except IntegrityError:
        existing = await role_svc.get(where)
        if existing is None:
            raise
        return await _update_role_display_name(
            role_svc,
            where=where,
            role=existing,
            display_name=template.display_name,
        )


async def _resolve_permission_object_id(
    perm_obj_svc: Any,
    *,
    permission_object: str,
) -> UUID:
    namespace, name = _split_key(permission_object)
    obj: PermissionObjectDE | None = await perm_obj_svc.get(
        {"namespace": namespace, "name": name},
        columns=("id",),
    )
    if obj is None or obj.id is None:
        raise RuntimeError(
            f"Default tenant grant references unknown permission object "
            f"{permission_object!r}."
        )
    return obj.id


async def _resolve_permission_type_id(
    perm_type_svc: Any,
    *,
    permission_type: str,
) -> UUID:
    namespace, name = _split_key(permission_type)
    typ: PermissionTypeDE | None = await perm_type_svc.get(
        {"namespace": namespace, "name": name},
        columns=("id",),
    )
    if typ is None or typ.id is None:
        raise RuntimeError(
            f"Default tenant grant references unknown permission type "
            f"{permission_type!r}."
        )
    return typ.id


async def _update_permission_entry(
    perm_entry_svc: Any,
    *,
    where: dict[str, Any],
    entry: PermissionEntryDE,
    permitted: bool,
) -> PermissionEntryDE:
    if entry.permitted == permitted:
        return entry

    updated = await perm_entry_svc.update(where, {"permitted": permitted})
    if updated is not None:
        return updated

    refreshed = await perm_entry_svc.get(where)
    if refreshed is None:
        raise RuntimeError(
            "Tenant permission entry disappeared during template materialization."
        )
    return refreshed


async def _ensure_permission_entry(
    perm_entry_svc: Any,
    *,
    tenant_id: UUID,
    role_id: UUID,
    permission_object_id: UUID,
    permission_type_id: UUID,
    grant: DefaultTenantTemplateGrant,
) -> PermissionEntryDE:
    permitted = bool(grant.permitted)
    where = {
        "tenant_id": tenant_id,
        "role_id": role_id,
        "permission_object_id": permission_object_id,
        "permission_type_id": permission_type_id,
    }
    existing = await perm_entry_svc.get(where)
    if existing is not None:
        return await _update_permission_entry(
            perm_entry_svc,
            where=where,
            entry=existing,
            permitted=permitted,
        )

    try:
        return await perm_entry_svc.create(
            {
                **where,
                "permitted": permitted,
            }
        )
    except IntegrityError:
        existing = await perm_entry_svc.get(where)
        if existing is None:
            raise
        return await _update_permission_entry(
            perm_entry_svc,
            where=where,
            entry=existing,
            permitted=permitted,
        )


async def materialize_tenant_role_templates(
    *,
    tenant_id: UUID,
    registry: IAdminRegistry,
) -> None:
    """
    Materialize registered tenant role templates and default grants for one tenant.

    The helper is idempotent: existing template-backed roles are updated in place for
    display-name drift, existing grants are updated for permitted-value drift, and
    operator-created memberships, roles, and grants are left intact.
    """
    manifest = registry.build_seed_manifest()
    if not manifest.tenant_role_templates and not manifest.default_tenant_grants:
        return

    role_svc = _service_for(registry, _EDM_ROLE)
    roles_by_template_key: dict[str, RoleDE] = {}
    for template in manifest.tenant_role_templates:
        role = await _ensure_role(
            role_svc,
            tenant_id=tenant_id,
            template=template,
        )
        if role.id is None:
            raise RuntimeError(
                f"Materialized tenant role {template.key!r} has no id."
            )
        roles_by_template_key[_norm_key(template.key)] = role

    if not manifest.default_tenant_grants:
        return

    perm_entry_svc = _service_for(registry, _EDM_PERMISSION_ENTRY)
    perm_obj_svc = _service_for(registry, _EDM_PERMISSION_OBJECT)
    perm_type_svc = _service_for(registry, _EDM_PERMISSION_TYPE)
    permission_object_ids: dict[str, UUID] = {}
    permission_type_ids: dict[str, UUID] = {}

    for grant in manifest.default_tenant_grants:
        template_key = _norm_key(grant.tenant_role_template)
        role = roles_by_template_key.get(template_key)
        if role is None or role.id is None:
            raise RuntimeError(
                "Default tenant grant references undeclared tenant role template "
                f"{grant.tenant_role_template!r}."
            )

        object_key = _norm_key(grant.permission_object)
        type_key = _norm_key(grant.permission_type)
        if object_key not in permission_object_ids:
            permission_object_ids[object_key] = await _resolve_permission_object_id(
                perm_obj_svc,
                permission_object=object_key,
            )
        if type_key not in permission_type_ids:
            permission_type_ids[type_key] = await _resolve_permission_type_id(
                perm_type_svc,
                permission_type=type_key,
            )

        await _ensure_permission_entry(
            perm_entry_svc,
            tenant_id=tenant_id,
            role_id=role.id,
            permission_object_id=permission_object_ids[object_key],
            permission_type_id=permission_type_ids[type_key],
            grant=grant,
        )
