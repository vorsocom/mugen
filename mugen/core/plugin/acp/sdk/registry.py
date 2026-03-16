"""
Provides an implementation of IAdminRegistry.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

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
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import AdminResource, SoftDeleteMode
from mugen.core.plugin.acp.contract.sdk.seed import AdminSeedManifest, SystemFlagDef
from mugen.core.utility.rgql.model import EdmModel, EdmType, EntitySet


def _norm_token(s: str) -> str:
    return s.strip().lower()


def _norm_key(key: str) -> str:
    """
    Normalize compound keys like "billing:invoice" / "admin:read".
    """
    k = key.strip()
    if ":" not in k:
        raise ValueError(f"Invalid key '{key}': expected '<namespace>:<name>'")
    ns, name = k.split(":", 1)
    ns_n = _norm_token(ns)
    name_n = _norm_token(name)
    if not ns_n or not name_n:
        raise ValueError(f"Invalid key '{key}': empty namespace or name")
    return f"{ns_n}:{name_n}"


_TITLE_CASE_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _is_title_case(name: str) -> bool:
    return bool(name) and bool(_TITLE_CASE_RE.match(name))


# pylint: disable=too-many-instance-attributes
# pylint: disable=too-many-public-methods
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
# pylint: disable=broad-exception-caught
@dataclass
class AdminRegistry(IAdminRegistry):
    """
    An implementation of IAdminRegistry.

    Configuration flags:
    - strict_permission_decls:
        If True, freeze() validates that referenced permission objects/types exist.
        If False, freeze() skips those validations.
    """

    _edm_services: dict[str, Any] = field(default_factory=dict)
    _tables: dict[str, Table] = field(default_factory=dict)

    _schema_types: dict[str, EdmType] = field(default_factory=dict)
    _schema_sets: dict[str, EntitySet] = field(default_factory=dict)
    _schema_index: dict[str, str] = field(default_factory=dict)

    _resources: list[AdminResource] = field(default_factory=list)
    _by_entity_set: dict[str, AdminResource] = field(default_factory=dict)
    _by_edm_type: dict[str, AdminResource] = field(default_factory=dict)

    # Declarative runtime binding specs
    _table_specs: list[TableSpec] = field(default_factory=list)
    _edm_type_specs: list[EdmTypeSpec] = field(default_factory=list)
    _service_specs: list[RelationalServiceSpec] = field(default_factory=list)

    _permission_objects: dict[str, PermissionObjectDef] = field(
        default_factory=dict
    )  # key -> def
    _permission_types: dict[str, PermissionTypeDef] = field(
        default_factory=dict
    )  # key -> def
    _global_roles: dict[str, GlobalRoleDef] = field(default_factory=dict)  # key -> def
    _tenant_role_templates: dict[str, TenantRoleTemplateDef] = field(
        default_factory=dict
    )  # key -> def

    _default_global_grants: list[DefaultGlobalGrant] = field(default_factory=list)
    _default_tenant_grants: list[DefaultTenantTemplateGrant] = field(
        default_factory=list
    )

    _system_flags: dict[str, SystemFlagDef] = field(default_factory=dict)  # key -> def

    # Behavior flags
    strict_permission_decls: bool = True

    _frozen: bool = False

    @property
    def edm_services(self) -> Mapping[str, Any]:
        return dict(self._edm_services)

    @property
    def resources(self) -> Mapping[str, AdminResource]:
        return dict({r.edm_type_name: r for r in self._resources})

    @property
    def schema(self) -> EdmModel:
        return EdmModel(
            types=dict(self._schema_types),
            entity_sets=dict(self._schema_sets),
        )

    @property
    def schema_index(self) -> Mapping[str, str]:
        return self._schema_index

    @property
    def tables(self) -> Mapping[str, Table]:
        return dict(self._tables)

    # -------------------------
    # Lifecycle
    # -------------------------

    def freeze(self, seeding: bool = False) -> None:
        """
        Freeze the registry and validate cross-references.

        With explicit AdminPermissions, this performs strong validation:
        - Resource permissions must be present and non-empty.
        - If strict_permission_decls=True, all referenced permission keys must be
          registered.
        - Grants must reference registered permission keys (and declared roles/templates
          if provided).
        """
        if self._frozen:
            return

        errors: list[str] = []

        # --- Validate resources (structure + key normalization) ---
        for r in self._resources:
            # Required core fields
            if not r.namespace or not r.namespace.strip():
                errors.append(f"Resource '{r.entity_set}' has empty namespace.")
            if not r.entity_set or not r.entity_set.strip():
                errors.append("Resource has empty entity_set.")
            if not r.edm_type_name or not r.edm_type_name.strip():
                errors.append(f"Resource '{r.entity_set}' has empty edm_type.")
            if not r.service_key or not r.service_key.strip():
                errors.append(f"Resource '{r.entity_set}' has empty service_key.")

            # Required permission fields (no defaults exist now)
            p = r.permissions
            for field_name in (
                "permission_object",
                "read",
                "create",
                "update",
                "delete",
                "manage",
            ):
                val = getattr(p, field_name)
                if not val or not str(val).strip():
                    errors.append(
                        f"Resource '{r.entity_set}' permissions.{field_name} is empty."
                    )

            # Normalize and validate keys exist (strict mode)
            if self.strict_permission_decls:
                try:
                    pobj = _norm_key(p.permission_object)
                except Exception as e:
                    errors.append(
                        f"Resource '{r.entity_set}' has invalid permission_object"
                        f" '{p.permission_object}': {e}"
                    )
                    pobj = None

                if pobj and pobj not in self._permission_objects:
                    errors.append(
                        f"Resource '{r.entity_set}' references unknown permission"
                        f" object '{pobj}'."
                    )

                for field_name in ("read", "create", "update", "delete", "manage"):
                    raw = getattr(p, field_name)
                    try:
                        k = _norm_key(raw)
                    except Exception as e:
                        errors.append(
                            f"Resource '{r.entity_set}' has invalid permission type"
                            f" '{raw}' in permissions.{field_name}: {e}"
                        )
                        continue
                    if k not in self._permission_types:
                        errors.append(
                            f"Resource '{r.entity_set}' references unknown permission"
                            f" type '{k}'."
                        )

                # Actions: require every action permission type to be registered.
                # If you want to support "" meaning "use manage", replace this
                # check accordingly.
                for action_name, action_decl in r.capabilities.actions.items():
                    if not isinstance(action_decl, dict):
                        errors.append(
                            f"Resource '{r.entity_set}' action '{action_name}' spec"
                            " should be a dict."
                        )
                        continue

                    action_perm = action_decl.get("perm")
                    if not action_perm or not action_perm.strip():
                        errors.append(
                            f"Resource '{r.entity_set}' action '{action_name}' has"
                            " empty permission type."
                        )
                        continue
                    try:
                        k = _norm_key(action_perm)
                    except Exception as e:
                        errors.append(
                            f"Resource '{r.entity_set}' action '{action_name}' has"
                            f" invalid permission type '{action_perm}': {e}"
                        )
                        continue
                    if k not in self._permission_types:
                        errors.append(
                            f"Resource '{r.entity_set}' action '{action_name}'"
                            f" references unknown permission type '{k}'."
                        )

            try:
                policy = r.behavior.soft_delete
            except Exception:
                errors.append(
                    f"Resource '{r.entity_set}' has no behavior.soft_delete policy"
                    " configured."
                )
                policy = None

            # Resolve the EDM type name regardless of older/newer attribute naming.
            type_name = (
                getattr(r, "edm_type_name", None) or getattr(r, "edm_type", None) or ""
            )

            # If policy missing, don't cascade further errors.
            if policy is not None:
                # 1) Mode NONE: column must be unset and restore semantics must be off.
                if policy.mode == SoftDeleteMode.NONE:
                    if policy.column:
                        errors.append(
                            f"Resource '{r.entity_set}' soft_delete.mode is NONE but"
                            f" column is set ('{policy.column}')."
                        )
                    if policy.allow_restore:
                        errors.append(
                            f"Resource '{r.entity_set}' soft_delete.mode is NONE but"
                            " allow_restore=True."
                        )

                # 2) Mode TIMESTAMP/FLAG: column must be present, TitleCase, and exist
                # on EDM type.
                else:
                    if not policy.column or not str(policy.column).strip():
                        errors.append(
                            f"Resource '{r.entity_set}' soft_delete.mode is"
                            f" {policy.mode.value!r} but soft_delete.column is empty."
                        )
                    else:
                        col = str(policy.column).strip()

                        # TitleCase / PascalCase enforcement (no underscores/spaces,
                        # must start uppercase). You said SoftDeletePolicy.column is
                        # intended to be TitleCase.
                        if (not col[0].isupper()) or ("_" in col) or (" " in col):
                            errors.append(
                                f"Resource '{r.entity_set}' soft_delete.column must be"
                                f" TitleCase (PascalCase). Got: '{col}'."
                            )

                        # Validate that the EDM type exists and has the property.
                        edm_type = (
                            self._schema_types.get(type_name) if type_name else None
                        )
                        if edm_type is None:
                            if not seeding:
                                errors.append(
                                    f"Resource '{r.entity_set}' references unknown EDM"
                                    f" type '{type_name}'."
                                )
                        else:
                            if col not in edm_type.properties:
                                errors.append(
                                    f"Resource '{r.entity_set}' soft_delete.column"
                                    f" '{col}' does not exist on EDM type"
                                    f" '{type_name}'."
                                )
                            else:
                                prop = edm_type.properties[col]

                                # Mode-specific checks
                                if policy.mode == SoftDeleteMode.TIMESTAMP:
                                    # For TIMESTAMP deletes, typical semantics require
                                    # nullable=True (active rows have NULL DeletedAt).
                                    if prop.nullable is False:
                                        errors.append(
                                            f"Resource '{r.entity_set}'"
                                            " soft_delete.mode=TIMESTAMP but EDM"
                                            f" property '{type_name}.{col}' is not"
                                            " nullable."
                                        )

                                    # Optional: sanity check the EDM type reference
                                    # (best-effort). (Leave permissive; your system
                                    # may use different EDM datetime types.)
                                    tname = getattr(prop.type, "name", "")
                                    if tname and (
                                        "DateTime" not in tname and "Time" not in tname
                                    ):
                                        errors.append(
                                            f"Resource '{r.entity_set}'"
                                            " soft_delete.mode=TIMESTAMP but"
                                            f" '{type_name}.{col}' type looks"
                                            f" non-temporal ({tname})."
                                        )

                                elif policy.mode == SoftDeleteMode.FLAG:
                                    # Require explicit deleted_value for flag semantics.
                                    if policy.deleted_value is None:
                                        errors.append(
                                            f"Resource '{r.entity_set}'"
                                            " soft_delete.mode=FLAG but deleted_value"
                                            " is None."
                                        )

                                    # Optional: sanity check boolean-like EDM type
                                    tname = getattr(prop.type, "name", "")
                                    if tname and ("Boolean" not in tname):
                                        errors.append(
                                            f"Resource '{r.entity_set}'"
                                            " soft_delete.mode=FLAG but"
                                            f" '{type_name}.{col}' type looks"
                                            f" non-boolean ({tname})."
                                        )

        # --- Validate default grants -> permission keys ---
        if self.strict_permission_decls:
            for g in self._default_global_grants:
                try:
                    pobj = _norm_key(g.permission_object)
                except Exception as e:
                    errors.append(
                        "DefaultGlobalGrant has invalid permission_object"
                        f" '{g.permission_object}': {e}"
                    )
                    pobj = None
                try:
                    ptyp = _norm_key(g.permission_type)
                except Exception as e:
                    errors.append(
                        "DefaultGlobalGrant has invalid permission_type"
                        f" '{g.permission_type}': {e}"
                    )
                    ptyp = None

                if pobj and pobj not in self._permission_objects:
                    errors.append(
                        f"DefaultGlobalGrant for role '{g.global_role}' references"
                        f" unknown permission object '{pobj}'."
                    )
                if ptyp and ptyp not in self._permission_types:
                    errors.append(
                        f"DefaultGlobalGrant for role '{g.global_role}' references"
                        f" unknown permission type '{ptyp}'."
                    )

            for g in self._default_tenant_grants:
                try:
                    pobj = _norm_key(g.permission_object)
                except Exception as e:
                    errors.append(
                        "DefaultTenantTemplateGrant has invalid permission_object"
                        f" '{g.permission_object}': {e}"
                    )
                    pobj = None
                try:
                    ptyp = _norm_key(g.permission_type)
                except Exception as e:
                    errors.append(
                        "DefaultTenantTemplateGrant has invalid permission_type"
                        f" '{g.permission_type}': {e}"
                    )
                    ptyp = None

                if pobj and pobj not in self._permission_objects:
                    errors.append(
                        "DefaultTenantTemplateGrant for template"
                        f" '{g.tenant_role_template}' references unknown permission"
                        f" object '{pobj}'."
                    )
                if ptyp and ptyp not in self._permission_types:
                    errors.append(
                        "DefaultTenantTemplateGrant for template"
                        f" '{g.tenant_role_template}' references unknown permission"
                        f" type '{ptyp}'."
                    )

        # --- Validate grants -> roles/templates if declared in registry ---
        if self._global_roles:
            declared = set(self._global_roles.keys())
            for g in self._default_global_grants:
                if _norm_key(g.global_role) not in declared:
                    errors.append(
                        "DefaultGlobalGrant references undeclared global role"
                        f" '{g.global_role}'."
                    )

        if self._tenant_role_templates:
            declared = set(self._tenant_role_templates.keys())
            for g in self._default_tenant_grants:
                if _norm_key(g.tenant_role_template) not in declared:
                    errors.append(
                        "DefaultTenantTemplateGrant references undeclared tenant role"
                        f" template '{g.tenant_role_template}'."
                    )

        if not seeding:
            schema = self.schema  # EdmModel
            for r in self._resources:
                if not r.behavior.rgql_enabled:
                    continue  # only enforce for RGQL-enabled resources

                try:
                    src_type = schema.get_type(r.edm_type_name)
                except KeyError:
                    errors.append(
                        f"Resource '{r.entity_set}' edm_type '{r.edm_type_name}' not"
                        " found in schema."
                    )
                    continue

                for nav_name, nav in src_type.nav_properties.items():
                    # Ensure the target type exists (helps catch typos early)
                    if nav.target_type.name not in schema.types:
                        errors.append(
                            f"{src_type.name}.{nav_name} targets unknown type"
                            f" '{nav.target_type.name}'."
                        )
                        continue

                    if nav.target_type.is_collection:
                        if not nav.target_fk or not nav.target_fk.strip():
                            errors.append(
                                f"{src_type.name}.{nav_name} is a collection nav and"
                                " must set target_fk."
                            )
                    else:
                        if not nav.source_fk or not nav.source_fk.strip():
                            errors.append(
                                f"{src_type.name}.{nav_name} is a single nav and must"
                                " set source_fk."
                            )

        if errors:
            raise RuntimeError(
                "AdminRegistry validation failed:\n- " + "\n- ".join(errors)
            )

        self._frozen = True

    def _ensure_writable(self) -> None:
        if self._frozen:
            raise RuntimeError(
                "AdminRegistry is frozen; registrations are not allowed."
            )

    # -------------------------
    # EDM services
    # -------------------------

    def register_edm_service(self, edm_type_name: str, service: Any) -> None:
        self._ensure_writable()
        if (
            edm_type_name in self._edm_services
            and self._edm_services[edm_type_name] is not service
        ):
            raise ValueError(
                f"EdmType {edm_type_name!r} already has a registered service."
            )
        self._edm_services[edm_type_name] = service

    def get_edm_service(self, service_key: str) -> Any:
        try:
            return self._edm_services[service_key]
        except KeyError as e:
            raise KeyError(f"No service registered for key {service_key!r}") from e

    # -------------------------
    # Resources
    # -------------------------

    def register_resource(self, resource: AdminResource) -> None:
        """
        Register an AdminResource.

        This performs immediate structural checks and enforces uniqueness by entity_set.
        Deeper cross-reference checks occur in freeze().
        """
        self._ensure_writable()

        key = resource.entity_set.lower()
        if key in self._by_entity_set:
            raise ValueError(
                f"Duplicate AdminResource entity_set: {resource.entity_set}"
            )

        # Basic structure checks early (fail fast)
        if not resource.permissions:
            raise ValueError(
                f"Resource '{resource.entity_set}' is missing permissions."
            )
        for field_name in (
            "permission_object",
            "read",
            "create",
            "update",
            "delete",
            "manage",
        ):
            val = getattr(resource.permissions, field_name)
            if not val or not str(val).strip():
                raise ValueError(
                    f"Resource '{resource.entity_set}' permissions.{field_name} is"
                    " empty."
                )

        self._resources.append(resource)
        self._by_entity_set[key] = resource
        self._by_edm_type[resource.edm_type_name] = resource

    def get_resource(self, entity_set: str) -> AdminResource:
        try:
            return self._by_entity_set[entity_set.lower()]
        except KeyError as e:
            raise KeyError(f"Unknown entity_set '{entity_set}'") from e

    def get_resource_by_type(self, edm_type_name: str) -> AdminResource:
        try:
            return self._by_edm_type[edm_type_name]
        except KeyError as e:
            raise KeyError(f"Unknown edm_type_name '{edm_type_name}'") from e

    # -------------------------
    # Runtime binding specs (pure)
    # -------------------------

    def register_table_spec(self, spec: TableSpec) -> None:
        self._ensure_writable()
        # enforce uniqueness on table_name
        if any(s.table_name == spec.table_name for s in self._table_specs):
            raise ValueError(f"Duplicate TableSpec for {spec.table_name!r}")
        self._table_specs.append(spec)

    def register_edm_type_spec(self, spec: EdmTypeSpec) -> None:
        self._ensure_writable()
        if any(s.edm_type_name == spec.edm_type_name for s in self._edm_type_specs):
            raise ValueError(f"Duplicate EdmTypeSpec for {spec.edm_type_name!r}")
        self._edm_type_specs.append(spec)

    def register_service_spec(self, spec: RelationalServiceSpec) -> None:
        self._ensure_writable()
        if any(s.service_key == spec.service_key for s in self._service_specs):
            raise ValueError(f"Duplicate ServiceSpec for {spec.service_key!r}")
        self._service_specs.append(spec)

    def table_specs(self) -> list[TableSpec]:
        return list(self._table_specs)

    def edm_type_specs(self) -> list[EdmTypeSpec]:
        return list(self._edm_type_specs)

    def service_specs(self) -> list[RelationalServiceSpec]:
        return list(self._service_specs)

    # -------------------------
    # SystemFlags
    # -------------------------
    def register_system_flag(self, flag: SystemFlagDef) -> None:
        self._ensure_writable()
        key = _norm_key(flag.key)
        if key in self._system_flags:
            raise ValueError(f"System flag {flag.name} already registered.")
        self._system_flags[key] = flag

    # -------------------------
    # Tables
    # -------------------------

    def register_table(self, table_name: str, table: Table) -> None:
        self._ensure_writable()
        if table_name in self._tables and self._tables[table_name] is not table:
            raise ValueError(f"Table {table_name} already registered.")
        self._tables[table_name] = table

    def get_table(self, table_name: str) -> Table:
        try:
            return self._tables[table_name]
        except KeyError as e:
            raise KeyError(f"No table with name {table_name!r} registered.") from e

    # -------------------------
    # EDM schema
    # -------------------------

    def register_edm_schema(
        self,
        *,
        types: Mapping[str, EdmType],
        entity_sets: Mapping[str, EntitySet],
    ) -> None:
        self._ensure_writable()

        for k in types:
            if k in self._schema_types:
                raise ValueError(f"EdmType {k!r} already registered.")

        for k in entity_sets:
            if k in self._schema_sets:
                raise ValueError(f"EntitySet {k!r} already registered.")
            self._schema_index[k] = entity_sets[k].type.name

        self._schema_types.update(types)
        self._schema_sets.update(entity_sets)

    # -------------------------
    # Permissions / roles / grants
    # -------------------------

    def register_permission_object(self, obj: PermissionObjectDef) -> None:
        self._ensure_writable()
        key = _norm_key(obj.key)
        if key in self._permission_objects:
            raise ValueError(f"PermissionObject {key!r} already registered.")
        self._permission_objects[key] = PermissionObjectDef(
            namespace=obj.namespace,
            name=obj.name,
        )

    def register_permission_type(self, typ: PermissionTypeDef) -> None:
        self._ensure_writable()
        key = _norm_key(typ.key)
        if key in self._permission_types:
            raise ValueError(f"PermissionType {key!r} already registered.")
        self._permission_types[key] = PermissionTypeDef(
            namespace=typ.namespace,
            name=typ.name,
        )

    def register_global_role(self, role: GlobalRoleDef) -> None:
        self._ensure_writable()
        key = _norm_key(role.key)
        if key in self._global_roles:
            raise ValueError(f"GlobalRole {role.name!r} already registered.")
        self._global_roles[key] = GlobalRoleDef(
            namespace=role.namespace,
            name=role.name,
            display_name=role.display_name,
        )

    def register_tenant_role_template(self, role: TenantRoleTemplateDef) -> None:
        self._ensure_writable()
        key = _norm_key(role.key)
        if key in self._tenant_role_templates:
            raise ValueError(f"TenantRoleTemplate {role.name!r} already registered.")
        self._tenant_role_templates[key] = TenantRoleTemplateDef(
            namespace=role.namespace,
            name=role.name,
            display_name=role.display_name,
        )

    def register_default_global_grant(self, grant: DefaultGlobalGrant) -> None:
        self._ensure_writable()
        self._default_global_grants.append(
            DefaultGlobalGrant(
                global_role=_norm_key(grant.global_role),
                permission_object=_norm_key(grant.permission_object),
                permission_type=_norm_key(grant.permission_type),
                permitted=bool(grant.permitted),
            )
        )

    def register_default_global_grants(
        self, grants: Iterable[DefaultGlobalGrant]
    ) -> None:
        for g in grants:
            self.register_default_global_grant(g)

    def register_default_tenant_grant(self, grant: DefaultTenantTemplateGrant) -> None:
        self._ensure_writable()
        self._default_tenant_grants.append(
            DefaultTenantTemplateGrant(
                tenant_role_template=_norm_key(grant.tenant_role_template),
                permission_object=_norm_key(grant.permission_object),
                permission_type=_norm_key(grant.permission_type),
                permitted=bool(grant.permitted),
            )
        )

    def register_default_tenant_grants(
        self, grants: Iterable[DefaultTenantTemplateGrant]
    ) -> None:
        for g in grants:
            self.register_default_tenant_grant(g)

    # -------------------------
    # Seed manifest
    # -------------------------

    def build_seed_manifest(self) -> AdminSeedManifest:
        """
        Build a deterministic seed manifest for Alembic.

        Ordering is normalized so that seed application is stable across load order.
        """
        self.freeze(seeding=True)

        perm_objects = [
            self._permission_objects[k] for k in sorted(self._permission_objects)
        ]
        perm_types = [self._permission_types[k] for k in sorted(self._permission_types)]
        global_roles = [self._global_roles[k] for k in sorted(self._global_roles)]
        tenant_templates = [
            self._tenant_role_templates[k] for k in sorted(self._tenant_role_templates)
        ]

        global_grants = sorted(
            self._default_global_grants,
            key=lambda g: (
                _norm_token(g.global_role),
                _norm_key(g.permission_object),
                _norm_key(g.permission_type),
                g.permitted,
            ),
        )
        tenant_grants = sorted(
            self._default_tenant_grants,
            key=lambda g: (
                _norm_token(g.tenant_role_template),
                _norm_key(g.permission_object),
                _norm_key(g.permission_type),
                g.permitted,
            ),
        )

        system_flags = [self._system_flags[k] for k in sorted(self._system_flags)]

        return AdminSeedManifest(
            permission_objects=perm_objects,
            permission_types=perm_types,
            global_roles=global_roles,
            tenant_role_templates=tenant_templates,
            default_global_grants=global_grants,
            default_tenant_grants=tenant_grants,
            system_flags=system_flags,
        )
