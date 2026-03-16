"""
Admin Control Plane (ACP) - Permission and role contracts.

This module defines purely declarative definitions for:
- Permission objects (nouns)
- Permission types (verbs)
- Global roles
- Tenant role templates
- Default grants (bootstrap policy)

These definitions are intended to be:
- Registered by plugins into an AdminRegistry, and
- Materialized into database rows via migrations or seed runners.

These are NOT the database models. They are the "desired state" declarations.
"""

from dataclasses import dataclass


def _key(namespace: str, name: str) -> str:
    return f"{namespace}:{name}"


@dataclass(frozen=True, slots=True)
class PermissionObjectDef:
    """
    Declarative permission object (noun).

    Example: namespace="billing", name="invoice" -> key="billing:invoice"

    The uniqueness identity is (namespace, name).
    """

    namespace: str
    name: str

    @property
    def key(self) -> str:
        """Get the reference key for the permission object."""
        return _key(self.namespace, self.name)


@dataclass(frozen=True, slots=True)
class PermissionTypeDef:
    """
    Declarative permission type (verb).

    Example: namespace="admin", name="read" -> key="admin:read"

    The uniqueness identity is (namespace, name).
    """

    namespace: str
    name: str

    @property
    def key(self) -> str:
        """Get reference key for the permission type."""
        return _key(self.namespace, self.name)


@dataclass(frozen=True, slots=True)
class GlobalRoleDef:
    """
    Declarative global role definition.

    The uniqueness identity is (namespace, name).

    display_name:
        A human readbale name for the role.
    """

    namespace: str
    name: str
    display_name: str

    @property
    def key(self) -> str:
        """Get reference key for the global role."""
        return _key(self.namespace, self.name)


@dataclass(frozen=True, slots=True)
class TenantRoleTemplateDef:
    """
    Declarative tenant role template definition.

    A tenant role template is a role definition that is materialized per-tenant.
    Typical pattern:
      - Seed templates once (migration).
      - When a tenant is created, instantiate concrete roles from templates and
        apply default tenant grants.

    The uniqueness identity is (namespace, name).

    display_name:
        A human readbale name for the role.
    """

    namespace: str
    name: str
    display_name: str

    @property
    def key(self) -> str:
        """Get reference key for the tenant role template."""
        return _key(self.namespace, self.name)


@dataclass(frozen=True, slots=True)
class DefaultGlobalGrant:
    """
    Declarative default grant targeting a global role.

    global_role:
        Must match a GlobalRoleDef.key.
    """

    global_role: str  # GlobalRoleDef.key
    permission_object: str  # PermissionObjectDef.key
    permission_type: str  # PermissionTypeDef.key
    permitted: bool = True


@dataclass(frozen=True, slots=True)
class DefaultTenantTemplateGrant:
    """
    Declarative default grant targeting a tenant role template.

    tenant_role_template:
        Must match a TenantRoleTemplateDef.key.
    """

    tenant_role_template: str  # TenantRoleTemplateDef.key
    permission_object: str  # PermissionObjectDef.key
    permission_type: str  # PermissionTypeDef.key
    permitted: bool = True
