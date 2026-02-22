"""
Admin plugin contribution entrypoint.

This module contributes the *core admin control-plane surface* into an
`IAdminRegistry`. It is intended to be called in two contexts:

1) Runtime (application startup):
   - A host application builds an `AdminRegistry`
   - Calls `contribute_all(...)` (or calls this `contribute(...)` directly)
   - Registers runtime EDM services separately (not done here)
   - Calls `registry.freeze()` (or relies on `build_seed_manifest()`)

2) Migrations (Alembic):
   - A migration builds an `AdminRegistry`
   - Calls `contribute_all(...)` which invokes this `contribute(...)`
   - Calls `manifest = registry.build_seed_manifest()`
   - Applies the manifest using the seed applicator (e.g., `apply_manifest(...)`)

Namespace conventions
---------------------
This module accepts two namespace values:

- `admin_namespace`:
  The configured Admin Control Plane (ACP) namespace. This module uses it for:
  - permission types (verbs), e.g. "<admin_namespace>:read"
  - permission objects (nouns) for admin-owned entities, e.g. "<admin_namespace>:tenant"
  - AdminResource namespace ownership
  - service key prefix (registry EDM service keys), e.g. "<admin_namespace>:ACP.User"

- `plugin_namespace`:
  The namespace of the currently contributing plugin as known by the loader.
  The core admin plugin does not currently use `plugin_namespace`, but it is
  part of the common contributor signature so that downstream plugins can use
  both namespaces:
  - admin_namespace for shared verbs / service-key conventions
  - plugin_namespace for plugin-owned nouns, flags, and optionally plugin roles

Contribution responsibilities
-----------------------------
This module registers:
- Permission types: read/create/update/delete/manage (owned by admin_namespace)
- Baseline global roles: administrator and authenticated (namespaced)
- Permission objects for each admin resource (owned by admin_namespace)
- Default global grants: administrator receives read/create/update/delete on all
  admin-owned permission objects
- AdminResources: capability flags (CRUD), behavior flags (soft-delete, RGQL),
  and action permission types (e.g., resetPassword requires manage)
- System flags: baseline ACP flags (e.g., "<admin_namespace>:installed")

Purity / import discipline
--------------------------
This module must remain "pure":
- No web framework imports (Quart/FastAPI), no DI container usage
- No global app state access
- Only uses contracts and simple helpers

This ensures it is safe to import and execute in Alembic migrations.
"""

import re
from typing import Any

from mugen.core.plugin.acp.api.validation.action import (
    UserActionResetPasswordAdmin,
    UserActionResetPasswordUser,
    UserActionUpdateProfile,
    UserActionUpdateRoles,
    UsersActionProvision,
)
from mugen.core.plugin.acp.api.validation.generic import (
    NoValidationSchema,
    RowVersionValidation,
)
from mugen.core.plugin.acp.api.validation.tenant import (
    TenantDomainCreateValidation,
    TenantDomainUpdateValidation,
    TenantInvitationCreateValidation,
    TenantInvitationUpdateValidation,
    TenantMembershipCreateValidation,
    TenantMembershipUpdateValidation,
)
from mugen.core.plugin.acp.contract.sdk.binding import (
    TableSpec,
    EdmTypeSpec,
    RelationalServiceSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    GlobalRoleDef,
    PermissionObjectDef,
    PermissionTypeDef,
)
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminCapabilities,
    AdminBehavior,
    AdminResource,
    CrudPolicy,
    SoftDeleteMode,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.utility.ns import AdminNs
from mugen.core.utility.string.case_conversion_helper import title_to_snake

_WORD_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+|\d+")


def _humanize(s: str) -> str:
    """Convert PascalCase/camelCase identifiers into a display title."""
    return " ".join(_WORD_RE.findall(s)).strip()


# pylint: disable=too-many-locals
def contribute(
    registry: IAdminRegistry,
    *,
    admin_namespace: str,
    plugin_namespace: str,
) -> None:
    """
    Contribute the core admin control-plane artifacts into `registry`.

    Parameters
    ----------
    registry:
        A mutable `IAdminRegistry` implementation (e.g., `AdminRegistry`).
        The registry must not be frozen at the time this function is called.

    admin_namespace:
        Configured ACP namespace. All admin-owned keys constructed by this
        contributor (permission types, permission objects, system flags, and
        resource namespace ownership) use this value.

    plugin_namespace:
        Namespace of the currently contributing plugin as loaded by the host.
        The core admin plugin does not currently use this parameter, but it is
        included to maintain a uniform contributor signature across the plugin
        ecosystem so downstream plugins can leverage both namespaces.

    Side effects
    ------------
    - Registers permission types under the admin namespace:
        "<admin_namespace>:read|create|update|delete|manage"
    - Registers baseline global roles:
        "<admin_namespace>:administrator", "<admin_namespace>:authenticated"
    - Registers a catalog of AdminResources for core admin entities, including:
        - entity_set (route segment / collection name)
        - edm_type ("ACP.<Entity>")
        - service_key ("<admin_namespace>:ACP.<Entity>")
        - permissions: generated via `AdminNs.perms(<object_name>)`
        - capabilities: allow_* flags and action permission types
        - behavior: soft_delete and rgql_enabled
    - Registers permission objects (nouns) for each catalog entry under the
      admin namespace.
    - Registers default global grants:
        administrator gets read/create/update/delete for all admin-owned objects.
    - Registers baseline system flags under the admin namespace (e.g., installed).

    Error behavior
    --------------
    Implementations of `IAdminRegistry` are expected to raise if:
    - called after freeze
    - duplicate keys are registered
    - keys are malformed (implementation-dependent normalization/validation)

    Notes
    -----
    - `allow_delete` defaults to False across the catalog because generic delete
      is typically unsafe; destructive operations should use explicit actions.
    - Action permission checks use the admin namespace verb keys.
    """
    admin_ns = AdminNs(admin_namespace)
    _plugin_ns = AdminNs(plugin_namespace)

    # -------------------------------------------------------------------------
    # 1) Permission types (verbs) owned by the configured admin namespace
    # -------------------------------------------------------------------------
    for verb in ("read", "create", "update", "delete", "manage"):
        registry.register_permission_type(
            PermissionTypeDef(namespace=admin_ns.ns, name=verb)
        )

    # -------------------------------------------------------------------------
    # 2) Baseline global roles (names must match your DB unique role identifier)
    # -------------------------------------------------------------------------
    registry.register_global_role(
        GlobalRoleDef(
            namespace=admin_ns.ns,
            name="administrator",
            display_name="Administrator",
        )
    )
    registry.register_global_role(
        GlobalRoleDef(
            namespace=admin_ns.ns,
            name="authenticated",
            display_name="Authenticated",
        )
    )

    # -------------------------------------------------------------------------
    # 3) Resource catalog (capabilities/behavior/actions live here)
    # -------------------------------------------------------------------------
    # Defaults:
    # - allow_delete=False (safer baseline; delete is rarely “generic”)
    # - soft_delete=True for identity/membership/invitation style entities
    resources: tuple[dict[str, Any], ...] = (
        # Permissions / authorization primitives
        {
            "set": "GlobalPermissionEntries",
            "entity": "GlobalPermissionEntry",
            "description": (
                "Grants binding global roles to permission objects and permission types"
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "GlobalRoles",
            "entity": "GlobalRole",
            "description": "Global (non-tenant) roles used for permission evaluation",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "GlobalRoleMemberships",
            "entity": "GlobalRoleMembership",
            "description": "User memberships for global (non-tenant) roles",
            "allow_create": True,
            "allow_update": False,
            "allow_delete": True,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "PermissionEntries",
            "entity": "PermissionEntry",
            "description": (
                "Grants binding tenant-scoped roles to permission objects and"
                " permission types"
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "PermissionObjects",
            "entity": "PermissionObject",
            "description": "Permission objects (nouns) identified by namespace:name",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "PermissionTypes",
            "entity": "PermissionType",
            "description": "Permission types (verbs) identified by namespace:name",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "Persons",
            "entity": "Person",
            "description": "Person profile associated with a user account",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "RefreshTokens",
            "entity": "RefreshToken",
            "description": (
                "Refresh tokens used to mint new access tokens for authenticated"
                " sessions"
            ),
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
            "actions": {
                "revoke": {
                    "perm": admin_ns.verb("manage"),
                    "schema": NoValidationSchema,
                },
            },
        },
        {
            "set": "Roles",
            "entity": "Role",
            "description": "Tenant-scoped roles used for permission evaluation",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "RoleMemberships",
            "entity": "RoleMembership",
            "description": "User memberships for tenant-scoped roles",
            "allow_create": True,
            "allow_update": False,
            "allow_delete": True,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "SystemFlags",
            "entity": "SystemFlag",
            "description": "System-wide feature flags and operational toggles",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
        },
        {
            "set": "Tenants",
            "entity": "Tenant",
            "description": "Tenant accounts and core tenant metadata",
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "actions": {
                "deactivate": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
                "reactivate": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
            },
            "crud": CrudPolicy(
                create_schema=("Name", "Slug"),
                update_schema=("Name", "Slug"),
            ),
        },
        {
            "set": "TenantDomains",
            "entity": "TenantDomain",
            "description": (
                "Domain names associated with tenants for routing and identity"
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": True,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
            "crud": CrudPolicy(
                create_schema=TenantDomainCreateValidation,
                update_schema=TenantDomainUpdateValidation,
            ),
        },
        {
            "set": "TenantInvitations",
            "entity": "TenantInvitation",
            "description": (
                "Invitations for users to join a tenant, including status and expiry"
            ),
            "allow_create": True,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
            "actions": {
                "resend": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
                "revoke": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
            },
            "crud": CrudPolicy(
                create_schema=TenantInvitationCreateValidation,
                update_schema=TenantInvitationUpdateValidation,
            ),
        },
        {
            "set": "TenantMemberships",
            "entity": "TenantMembership",
            "description": (
                "User memberships within a tenant, including status and lifecycle"
            ),
            "allow_create": True,
            "allow_update": True,
            "allow_delete": False,
            "allow_manage": False,
            "soft_delete": SoftDeletePolicy(),
            "actions": {
                "suspend": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
                "unsuspend": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
                "remove": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                },
            },
            "crud": CrudPolicy(
                create_schema=TenantMembershipCreateValidation,
                update_schema=TenantMembershipUpdateValidation,
            ),
        },
        {
            "set": "Users",
            "entity": "User",
            "description": "Administrative user accounts",
            "allow_create": False,
            "allow_update": False,
            "allow_delete": False,
            "allow_manage": True,
            "soft_delete": SoftDeletePolicy(
                mode=SoftDeleteMode.TIMESTAMP,
                column="DeletedAt",
                allow_restore=True,
                allow_hard_delete=False,
            ),
            "actions": {
                "delete": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "is_admin_action": True,
                },
                "lock": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "is_admin_action": True,
                },
                "provision": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UsersActionProvision,
                    "is_admin_action": True,
                },
                "resetpasswordadmin": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UserActionResetPasswordAdmin,
                    "is_admin_action": True,
                },
                "resetpassworduser": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UserActionResetPasswordUser,
                },
                "unlock": {
                    "perm": admin_ns.verb("manage"),
                    "schema": RowVersionValidation,
                    "is_admin_action": True,
                },
                "updateprofile": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UserActionUpdateProfile,
                },
                "updateroles": {
                    "perm": admin_ns.verb("manage"),
                    "schema": UserActionUpdateRoles,
                    "is_admin_action": True,
                },
            },
            "crud": CrudPolicy(
                create_schema=NoValidationSchema,
                update_schema=NoValidationSchema,
                delete_schema=NoValidationSchema,
            ),
        },
    )

    # -------------------------------------------------------------------------
    # 4) Permission objects (nouns) owned by configured admin namespace
    # -------------------------------------------------------------------------
    admin_objects: list[PermissionObjectDef] = []
    for r in resources:
        entity = r["entity"]
        obj_name = title_to_snake(entity)
        obj = PermissionObjectDef(admin_ns.ns, obj_name)
        admin_objects.append(obj)
        registry.register_permission_object(obj)

    # -------------------------------------------------------------------------
    # 5) Default grants (bootstrap policy)
    # -------------------------------------------------------------------------
    # Administrator gets broad access (read/create/update/delete) to
    # admin-owned objects.
    admin_obj_keys = [o.key for o in admin_objects]
    admin_verb_keys = [
        admin_ns.verb(v) for v in ("read", "create", "update", "delete", "manage")
    ]

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("administrator"), pobj, ptyp, True)
        for pobj in admin_obj_keys
        for ptyp in admin_verb_keys
    )

    registry.register_default_global_grants(
        DefaultGlobalGrant(admin_ns.key("authenticated"), pobj, ptyp, True)
        for pobj in (admin_ns.obj("user"),)
        for ptyp in (admin_ns.verb("read"), admin_ns.verb("manage"))
    )

    # -------------------------------------------------------------------------
    # 6) AdminResources
    # -------------------------------------------------------------------------
    for r in resources:
        entity_set = r["set"]
        entity = r["entity"]
        obj_name = title_to_snake(entity)
        obj = PermissionObjectDef(admin_ns.ns, obj_name)

        edm_type_name = f"ACP.{entity}"
        service_key = f"{admin_ns.ns}:{edm_type_name}"

        registry.register_resource(
            AdminResource(
                namespace=admin_ns.ns,
                entity_set=entity_set,
                edm_type_name=edm_type_name,
                perm_obj=obj.key,
                service_key=service_key,
                permissions=admin_ns.perms(obj_name),
                capabilities=AdminCapabilities(
                    allow_read=bool(r.get("allow_read", True)),
                    allow_create=bool(r.get("allow_create", False)),
                    allow_update=bool(r.get("allow_update", False)),
                    allow_delete=bool(r.get("allow_delete", False)),
                    allow_manage=bool(r.get("allow_manage", False)),
                    actions=dict(r.get("actions", {})),
                ),
                behavior=AdminBehavior(
                    soft_delete=r.get("soft_delete", SoftDeletePolicy()),
                    rgql_enabled=True,
                ),
                crud=r.get("crud", CrudPolicy()),
                title=_humanize(entity_set),
                description=r["description"],
            )
        )

        # -----------------------------------------------------------------
        # Declarative runtime binding specs (pure; materialized at runtime)
        # -----------------------------------------------------------------
        # Conventions:
        # - table name: "admin_<snake>"
        # - model module: mugen.core.plugin.acp.model.<snake>
        # - edm module: mugen.core.plugin.acp.edm.<snake> with "<snake>_type"
        # - service module: mugen.core.plugin.acp.service.<snake> with "<Entity>Service"
        registry.register_table_spec(
            TableSpec(
                table_name=f"admin_{obj_name}",
                table_provider=f"mugen.core.plugin.acp.model.{obj_name}:{entity}",
            )
        )

        registry.register_edm_type_spec(
            EdmTypeSpec(
                edm_type_name=edm_type_name,
                edm_provider=f"mugen.core.plugin.acp.edm:{obj_name}_type",
            )
        )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key=service_key,
                service_cls=f"mugen.core.plugin.acp.service.{obj_name}:{entity}Service",
                init_kwargs={"table": f"admin_{obj_name}"},
            )
        )
