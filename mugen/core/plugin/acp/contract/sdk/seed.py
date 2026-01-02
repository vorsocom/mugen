"""
Admin Control Plane (ACP) - Seed manifest.

This module defines a portable manifest of "desired state" declarations that can
be consumed by database seeding logic (e.g., Alembic migrations).

Design:
- The manifest contains only contract objects (dataclasses), not DB models.
- An "apply" function in migration code can upsert these into tables.

This allows plugins to remain lightweight: they register definitions in-process,
and migrations materialize them into database rows deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass

from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    DefaultTenantTemplateGrant,
    GlobalRoleDef,
    PermissionObjectDef,
    PermissionTypeDef,
    TenantRoleTemplateDef,
)


@dataclass(frozen=True, slots=True)
class SystemFlagDef:
    """
    Declarative system-wide flag owned by a plugin namespace.

    Key format:
        "<namespace>:<name>" where namespace is the plugin namespace.

    Fields:
    - description: admin-facing documentation
    - is_set: value to seed initially (not necessarily forced on update)
    """

    namespace: str
    name: str
    description: str | None = None
    is_set: bool | None = None

    @property
    def key(self) -> str:
        """Get the reference key for the system flag object."""
        return f"{self.namespace}:{self.name}"


@dataclass(frozen=True, slots=True)
class AdminSeedManifest:
    """
    The full declarative seed manifest.

    Notes:
    - This does not include AdminResources because AdminResources are routing/policy
      artifacts; seeding typically concerns roles/permissions/grants.

    Ordering:
    - Registry implementations should emit these lists in deterministic order.
      Seed logic should still be idempotent.
    """

    permission_objects: list[PermissionObjectDef]
    permission_types: list[PermissionTypeDef]

    global_roles: list[GlobalRoleDef]
    tenant_role_templates: list[TenantRoleTemplateDef]

    default_global_grants: list[DefaultGlobalGrant]
    default_tenant_grants: list[DefaultTenantTemplateGrant]

    system_flags: list[SystemFlagDef]
