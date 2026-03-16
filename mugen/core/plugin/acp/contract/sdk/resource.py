# mugen/core/plugin/admin/contract/resource.py
"""
Admin Control Plane (ACP) - Resource contract.

This module defines the public, framework-agnostic contract describing how an EDM
EntitySet is exposed in the Admin control plane.

IMPORTANT DESIGN RULE:
- This contract does not assume any fixed namespace (e.g., "admin").
- All permission keys must be provided as fully-qualified "<namespace>:<name>" strings.
- The configured admin plugin namespace (from TOML/DI) should be used consistently
  everywhere the admin plugin owns a namespaced identifier.

This file must remain pure: no framework imports, no DI, no database imports.
"""

from dataclasses import dataclass, field
import enum
from typing import Any, Mapping, Optional

from pydantic import BaseModel as PdModel

# pylint: disable=too-many-instance-attributes


@dataclass(frozen=True, slots=True)
class AdminPermissions:
    """
    Permission policy for a resource.

    All fields must be explicit and fully qualified:
      - permission_object: "<namespace>:<object>"
      - read/create/update/delete/manage: "<namespace>:<verb>"

    Rationale:
    - Prevents accidental hard-coded defaults ("admin:read") in a system where the
      admin namespace is configured at runtime.
    - Ensures resources remain portable across deployments with different
      admin namespaces.
    """

    permission_object: str
    read: str
    create: str
    update: str
    delete: str
    manage: str


@dataclass(frozen=True, slots=True)
class AdminCapabilities:
    """
    Declares which generic operations the Admin API should expose for a resource.

    Actions:
    - `actions` is an optional mapping declaring actions supported by a resource.
          - the mapping keys are the actions.
          - action metadata may include `required_capabilities`, a list of
            capability strings enforced by ACP sandbox dispatch.
    """

    allow_read: bool = True
    allow_create: bool = False
    allow_update: bool = False
    allow_delete: bool = False
    allow_manage: bool = False

    actions: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def op_allowed(self, op: str) -> bool:
        """Determine if a capability is allowed, given the operation name."""
        match op:
            case "read":
                return self.allow_read
            case "create":
                return self.allow_create
            case "update":
                return self.allow_update
            case "delete":
                return self.allow_delete
            case "manage":
                return self.allow_manage
            case _:
                return False


class SoftDeleteMode(enum.Enum):
    """Options for how soft delete is implemented."""

    NONE = "none"
    TIMESTAMP = "timestamp"
    FLAG = "flag"


@dataclass(frozen=True)
class SoftDeletePolicy:
    """Describes soft-delete implementation at exposed surface."""

    mode: SoftDeleteMode = SoftDeleteMode.NONE
    column: Optional[str] = None  # e.g., "DeletedAt" or "IsDeleted"
    deleted_value: Any | None = True  # only for FLAG, usually True
    include_deleted_default: bool = False
    allow_restore: bool = False
    allow_hard_delete: bool = True


@dataclass(frozen=True, slots=True)
class AdminBehavior:
    """
    Behavioral flags for the generic admin surface.
    """

    soft_delete: SoftDeletePolicy = field(default_factory=SoftDeletePolicy)
    rgql_enabled: bool = True
    rgql_max_expand_depth: Optional[int] = None


@dataclass(frozen=True)
class CrudPolicy:
    """Controls CRUD behaviour."""

    create_schema: PdModel | None = None
    update_schema: PdModel | None = None
    delete_schema: PdModel | None = None

    # concurrency
    require_if_match_on_update: bool = True
    require_if_match_on_delete: bool = True


@dataclass(frozen=True, slots=True)
class AdminResource:
    """
    Canonical binding between:
      - an EDM EntitySet (route segment),
      - an EDM Type (schema identity),
      - and an EDM-backed service (implementation),
    with admin-plane policy (permissions/capabilities/behavior).

    namespace:
      The owning plugin namespace. In your admin plugin, this should be the configured
      namespace from TOML/DI (e.g., "com.vorsocomputing.mugen.acp"), not a hard-coded
      label like "admin".

    entity_set:
      The EntitySet name used in routes: core/<entity_set>.

    edm_type:
      The EDM type name from your EDM schema (e.g., "ACP.User").

    perm_obj:
      The unprefixed EDM type name converted to snake case. Used as permission object
      name (e.g. user, system_flag).

    service_key:
      The registry key used to resolve the service implementing this EDM type.
      If your system resolves services via "{admin_namespace}:{edm_type}", then
      service_key should follow that convention.
    """

    namespace: str
    entity_set: str
    edm_type_name: str
    perm_obj: str
    service_key: str

    permissions: AdminPermissions
    capabilities: AdminCapabilities = field(default_factory=AdminCapabilities)
    behavior: AdminBehavior = field(default_factory=AdminBehavior)
    crud: CrudPolicy = field(default_factory=CrudPolicy)

    title: Optional[str] = None
    description: Optional[str] = None
