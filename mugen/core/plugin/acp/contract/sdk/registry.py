"""
Control-plane registry contract.

`IAdminRegistry` is the central aggregation point for:
- AdminResources (routing + policy bindings)
- EDM schema contributions (EdmTypes + EntitySets)
- EDM services (service instances keyed by EdmType name / service key convention)
- Seedable policy declarations (permission objects/types, roles/templates,
  default grants)
- Optional system flags (seedable operational toggles)
- Optional SQLAlchemy Table registrations (for metadata access / integration)

This contract is intentionally framework-agnostic:
- No DI assumptions
- No ORM assumptions (only SQLAlchemy Table type for optional registration)
- Callable from both runtime (app startup) and tooling (Alembic migrations)

Typical lifecycle:
1) Create a registry implementation (e.g., AdminRegistry)
2) Call contributor functions to register declarations/resources/services/schema
3) Call `freeze()` to finalize and validate the registry
4) Runtime: resolve resources/services via getters
5) Migrations: call `build_seed_manifest()` and apply it to the DB with an applicator
"""

from abc import ABC, abstractmethod
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy.sql.schema import Table

from mugen.core.plugin.acp.contract.sdk.binding import (
    TableSpec,
    EdmTypeSpec,
    RelationalServiceSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    DefaultTenantTemplateGrant,
    GlobalRoleDef,
    PermissionObjectDef,
    PermissionTypeDef,
    TenantRoleTemplateDef,
)
from mugen.core.plugin.acp.contract.sdk.resource import AdminResource
from mugen.core.plugin.acp.contract.sdk.seed import AdminSeedManifest, SystemFlagDef
from mugen.core.utility.rgql.model import EdmModel, EdmType, EntitySet


class IAdminRegistry(ABC):
    """
    Control-plane registry that extensions can contribute to.

    Implementations are expected to:
    - Allow mutation until `freeze()` is called, then become immutable
    - Validate cross-references at freeze time (recommended), e.g.:
        - resources reference permission types/objects that exist
        - grants reference roles/templates that exist
        - schema index consistency (entity_set -> edm_type)
    - Emit deterministic seed manifests for policy-related declarations

    Threading:
    - Unless an implementation explicitly states otherwise, treat registries as
      single-threaded and finalize at startup before request handling.
    """

    # ---------------------------------------------------------------------
    # Properties.
    # ---------------------------------------------------------------------

    @property
    @abstractmethod
    def edm_services(self) -> Mapping[str, Any]:
        """
        Get all registered EDM-related services.

        Keys:
        - Typically EdmType name (e.g. "ACP.User") or a service key convention
          (e.g. "<admin_namespace>:ACP.User") depending on your architecture.

        Values:
        - Singleton service instances (usually stateless or internally thread-safe).

        Error semantics:
        - Implementations may return a copy or a read-only mapping.
        """

    @property
    @abstractmethod
    def resources(self) -> Mapping[str, AdminResource]:
        """
        Get all registered AdminResources.

        Intended use:
        - Allow services or integration layers to reference reflected/declared
          resources.
        """

    @property
    @abstractmethod
    def schema(self) -> EdmModel:
        """
        Get the built EDM model.

        Expected behavior:
        - Returns the compiled EdmModel constructed from all `register_edm_schema`
          contributions.
        - Implementations may build lazily (on access) or eagerly (at freeze).
        - If no schema has been registered, implementations may return an empty
          EdmModel or raise (choose and document).
        """

    @property
    @abstractmethod
    def schema_index(self) -> Mapping[str, str]:
        """
        Get the registry's entity set name -> edm type mapping.

        Keys:
        - EntitySet names (route segments), e.g. "Users"
        Values:
        - EDM type names, e.g. "ACP.User"

        Intended use:
        - Fast lookup for routing, RGQL binding, and resource registration checks.
        """

    @property
    @abstractmethod
    def tables(self) -> Mapping[str, Table]:
        """
        Get all registered SQLAlchemy Tables.

        Intended use:
        - Allow services or integration layers to reference reflected/declared
          table metadata without re-importing model modules.

        Notes:
        - This is optional; some implementations may leave it empty.
        """

    # ---------------------------------------------------------------------
    # Registry lifecycle
    # ---------------------------------------------------------------------

    @abstractmethod
    def freeze(self) -> None:
        """
        Finalize the registry and prevent further modification.

        Expected behavior:
        - After freeze, all register_* methods should raise (ValueError/RuntimeError).
        - Perform cross-reference validation (recommended), such as:
            - resources refer to registered permission objects/types
            - grants refer to registered roles/templates
            - no duplicate keys for objects/types/roles/resources
        - Should be idempotent (calling multiple times is safe).
        """

    # ---------------------------------------------------------------------
    # Seedable policy: default grants
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_default_global_grant(self, grant: DefaultGlobalGrant) -> None:
        """
        Register a single default global grant.

        A DefaultGlobalGrant binds:
        - global_role ("<namespace>:<name>")
        - permission_object ("<namespace>:<object>")
        - permission_type ("<namespace>:<verb>")
        - permitted (bool)

        These grants are intended to be applied to the DB via a seed manifest.
        """

    @abstractmethod
    def register_default_global_grants(
        self, grants: Iterable[DefaultGlobalGrant]
    ) -> None:
        """
        Register multiple default global grants.

        Implementations should treat this as a convenience wrapper that calls
        `register_default_global_grant` for each item.
        """

    @abstractmethod
    def register_default_tenant_grant(self, grant: DefaultTenantTemplateGrant) -> None:
        """
        Register a single default tenant template grant.

        A DefaultTenantTemplateGrant binds:
        - tenant_role_template ("<namespace>:<name>")
        - permission_object ("<namespace>:<object>")
        - permission_type ("<namespace>:<verb>")
        - permitted (bool)

        Notes:
        - This is for template-based tenant provisioning.
        - Many deployments may not use tenant templates initially; implementations
          should still support it as an optional feature.
        """

    @abstractmethod
    def register_default_tenant_grants(
        self, grants: Iterable[DefaultTenantTemplateGrant]
    ) -> None:
        """
        Register multiple default tenant template grants.

        Implementations should treat this as a convenience wrapper that calls
        `register_default_tenant_grant` for each item.
        """

    # ---------------------------------------------------------------------
    # EDM service registration / lookup
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_edm_service(self, edm_type_name: str, service: Any) -> None:
        """
        Register an EDM-related service with the registry.

        Parameters
        ----------
        edm_type_name:
            The registry key used to resolve the service at runtime. Depending
            on your convention, this may be:
              - EdmType name: "ACP.User"
              - Namespaced service key: "<admin_namespace>:ACP.User"

        service:
            The service instance that implements operations for this EDM type.

        Expected behavior:
        - Enforce uniqueness for edm_type_name.
        - Raise if frozen.
        """

    @abstractmethod
    def get_edm_service(self, service_key: str) -> Any:
        """
        Resolve the singleton service instance for an EdmType name / service key.

        Error semantics:
        - Implementations should raise KeyError or a domain-specific exception
          if the service is not registered.
        """

    # ---------------------------------------------------------------------
    # Seedable policy: roles / permission objects / permission types
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_global_role(self, role: GlobalRoleDef) -> None:
        """
        Register a GlobalRole definition.

        Identity / keying
        -----------------
        Global roles are uniquely identified by (namespace, name) and are referenced
        elsewhere (e.g., DefaultGlobalGrant.global_role) using the fully-qualified key:

            "<namespace>:<name>"

        Intended use
        ------------
        - Seed manifest emission (roles are inserted/upserted by the applicator)
        - Enumeration in admin surfaces
        - Permission evaluation (global-role based grants)

        Implementations should:
        - enforce uniqueness after normalization
        - raise if the registry is frozen
        """

    @abstractmethod
    def register_tenant_role_template(self, role: TenantRoleTemplateDef) -> None:
        """
        Register a TenantRoleTemplate definition.

        Intended use:
        - Tenant provisioning: create standard tenant-scoped roles with seeded grants.
        """

    @abstractmethod
    def register_permission_object(self, obj: PermissionObjectDef) -> None:
        """
        Register a PermissionObject definition (a "noun").

        Key convention:
        - Typically "<namespace>:<name>" where namespace is the owning plugin namespace.

        Expected behavior:
        - Enforce uniqueness on (namespace, name) after normalization.
        """

    @abstractmethod
    def register_permission_type(self, typ: PermissionTypeDef) -> None:
        """
        Register a PermissionType definition (a "verb").

        Key convention:
        - Typically "<namespace>:<name>" where namespace is the owning control plane
          namespace (often the configured admin namespace).

        Expected behavior:
        - Enforce uniqueness on (namespace, name) after normalization.
        """

    # ---------------------------------------------------------------------
    # Admin resources (routing + policy)
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_resource(self, resource: AdminResource) -> None:
        """
        Register an AdminResource with the registry.

        An AdminResource binds:
        - entity_set: route segment / EntitySet name (e.g. "Users")
        - edm_type: schema identity (e.g. "ACP.User")
        - service_key: EDM service resolution key
        - permissions: fully qualified permission keys
        - capabilities/behavior: generic admin surface settings (CRUD + actions)

        Expected behavior:
        - Enforce unique entity_set.
        - Recommended: validate permissions are non-empty at registration time.
        - Recommended: perform deeper cross-reference validation in freeze().
        """

    @abstractmethod
    def get_resource(self, entity_set: str) -> AdminResource:
        """
        Resolve an AdminResource by entity set name.

        Parameters
        ----------
        entity_set:
            EntitySet name / route segment, typically case-insensitive.

        Error semantics:
        - Raise KeyError (or a domain exception) if not found.
        """

    @abstractmethod
    def get_resource_by_type(self, edm_type_name: str) -> AdminResource:
        """
        Resolve an AdminResource by EDM type name (e.g., "ACP.User").

        This is the key used by RGQL expansion (nav_type.name).
        """

    # ---------------------------------------------------------------------
    # Runtime binding specs (pure declarations)
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_table_spec(self, spec: TableSpec) -> None:
        """Register a declarative TableSpec."""

    @abstractmethod
    def register_edm_type_spec(self, spec: EdmTypeSpec) -> None:
        """Register a declarative EdmTypeSpec."""

    @abstractmethod
    def register_service_spec(self, spec: RelationalServiceSpec) -> None:
        """Register a declarative service spec for runtime instantiation."""

    @abstractmethod
    def table_specs(self) -> Sequence[TableSpec]:
        """Return all registered table specs (read-only)."""

    @abstractmethod
    def edm_type_specs(self) -> Sequence[EdmTypeSpec]:
        """Return all registered EDM type specs (read-only)."""

    @abstractmethod
    def service_specs(self) -> Sequence[RelationalServiceSpec]:
        """Return all registered service specs (read-only)."""

    # ---------------------------------------------------------------------
    # System flags (optional seedable artifact)
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_system_flag(self, flag: SystemFlagDef) -> None:
        """
        Register a SystemFlagDef.

        System flags are seedable, namespace-scoped operational toggles. They are
        best used for feature gates and emergency switches, not arbitrary config.

        Recommended seed semantics:
        - Insert the flag if missing.
        - Update metadata fields (description, mutability) deterministically.
        - Do NOT overwrite the operator-controlled value on conflict.
        """

    # ---------------------------------------------------------------------
    # Table registration / lookup
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_table(self, table_name: str, table: Table) -> None:
        """
        Register an SQLAlchemy Table under a logical name.

        Parameters
        ----------
        table_name:
            Logical name used for lookup; may or may not match the DB table name.

        table:
            SQLAlchemy Table object.

        Expected behavior:
        - Enforce uniqueness on table_name.
        """

    def register_tables(self, tables: Mapping[str, Table]) -> None:
        """
        Register multiple SQLAlchemy tables with the registry.

        This is a convenience method implemented in the interface.
        Implementations should enforce immutability via `register_table()`.
        """
        for name, table in tables.items():
            self.register_table(name, table)

    @abstractmethod
    def get_table(self, table_name: str) -> Table:
        """
        Resolve a previously registered SQLAlchemy Table.

        Error semantics:
        - Raise KeyError (or domain exception) if not found.
        """

    # ---------------------------------------------------------------------
    # EDM schema contributions
    # ---------------------------------------------------------------------

    @abstractmethod
    def register_edm_schema(
        self,
        *,
        types: Mapping[str, EdmType],
        entity_sets: Mapping[str, EntitySet],
    ) -> None:
        """
        Register EdmTypes and EntitySets from contributed extensions.

        Parameters
        ----------
        types:
            Mapping of EdmType name -> EdmType definition.

        entity_sets:
            Mapping of EntitySet name -> EntitySet definition.

        Expected behavior:
        - Merge contributed schema components into a single EdmModel.
        - Enforce uniqueness / collision rules for names.
        - Populate/refresh `schema_index` (entity_set -> edm_type name).
        """

    # ---------------------------------------------------------------------
    # Seed manifest
    # ---------------------------------------------------------------------

    @abstractmethod
    def build_seed_manifest(self) -> AdminSeedManifest:
        """
        Build and return a deterministic seed manifest.

        The manifest is the authoritative, declarative desired state for seedable
        control-plane artifacts (e.g., permission objects/types, roles/templates,
        default grants, system flags).

        Expected behavior:
        - Call `freeze()` implicitly or require freeze to have occurred.
        - Ensure deterministic ordering of items for stable migrations.
        - Do not include runtime-only registrations (services/resources) unless
          you explicitly decide to seed them (not typical).
        """
