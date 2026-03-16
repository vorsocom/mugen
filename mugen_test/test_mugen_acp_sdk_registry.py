"""Unit tests for mugen.core.plugin.acp.sdk.registry."""

from __future__ import annotations

import unittest

from sqlalchemy import Column, Integer, MetaData, String, Table

from mugen.core.plugin.acp.contract.sdk.binding import (
    EdmTypeSpec,
    RelationalServiceSpec,
    TableSpec,
)
from mugen.core.plugin.acp.contract.sdk.permission import (
    DefaultGlobalGrant,
    DefaultTenantTemplateGrant,
    GlobalRoleDef,
    PermissionObjectDef,
    PermissionTypeDef,
    TenantRoleTemplateDef,
)
from mugen.core.plugin.acp.contract.sdk.resource import (
    AdminBehavior,
    AdminCapabilities,
    AdminPermissions,
    AdminResource,
    SoftDeleteMode,
    SoftDeletePolicy,
)
from mugen.core.plugin.acp.contract.sdk.seed import SystemFlagDef
from mugen.core.plugin.acp.sdk.registry import (
    AdminRegistry,
    _is_title_case,
    _norm_key,
    _norm_token,
)
from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    EntitySet,
    TypeRef,
)


def _permissions(
    permission_object: str = "acp:user",
    read: str = "acp:read",
    create: str = "acp:create",
    update: str = "acp:update",
    delete: str = "acp:delete",
    manage: str = "acp:manage",
) -> AdminPermissions:
    return AdminPermissions(
        permission_object=permission_object,
        read=read,
        create=create,
        update=update,
        delete=delete,
        manage=manage,
    )


def _resource(
    *,
    namespace: str = "acp",
    entity_set: str = "Users",
    edm_type_name: str = "ACP.User",
    service_key: str = "svc.users",
    permissions: AdminPermissions | None = None,
    capabilities: AdminCapabilities | None = None,
    behavior: AdminBehavior | object | None = None,
) -> AdminResource:
    return AdminResource(
        namespace=namespace,
        entity_set=entity_set,
        edm_type_name=edm_type_name,
        perm_obj="user",
        service_key=service_key,
        permissions=permissions if permissions is not None else _permissions(),
        capabilities=capabilities if capabilities is not None else AdminCapabilities(),
        behavior=(
            behavior if behavior is not None else AdminBehavior(rgql_enabled=False)
        ),
    )


def _edm_type(
    name: str,
    *,
    properties: dict[str, EdmProperty] | None = None,
    nav_properties: dict[str, EdmNavigationProperty] | None = None,
) -> EdmType:
    return EdmType(
        name=name,
        kind="entity",
        properties=properties or {},
        nav_properties=nav_properties or {},
    )


def _register_acp_perms(registry: AdminRegistry, *, object_name: str = "user") -> None:
    registry.register_permission_object(
        PermissionObjectDef(namespace="acp", name=object_name)
    )
    for perm_name in ("read", "create", "update", "delete", "manage", "approve"):
        registry.register_permission_type(
            PermissionTypeDef(namespace="acp", name=perm_name)
        )


class _BehaviorWithoutSoftDelete:
    rgql_enabled = False

    @property
    def soft_delete(self):
        raise RuntimeError("no soft-delete policy")


class TestMugenAcpSdkRegistry(unittest.TestCase):
    """Branch and error-path tests for AdminRegistry."""

    def test_norm_helpers(self) -> None:
        self.assertEqual(_norm_token("  ACP  "), "acp")
        self.assertEqual(_norm_key(" ACP:Read "), "acp:read")

        with self.assertRaisesRegex(ValueError, "expected '<namespace>:<name>'"):
            _norm_key("missing-separator")
        with self.assertRaisesRegex(ValueError, "empty namespace or name"):
            _norm_key("acp:")

        self.assertTrue(_is_title_case("DeletedAt"))
        self.assertFalse(_is_title_case("deleted_at"))

    def test_registry_property_views(self) -> None:
        registry = AdminRegistry()
        metadata = MetaData()
        users_table = Table(
            "users",
            metadata,
            Column("id", Integer, primary_key=True),
        )

        service = object()
        registry.register_edm_service("svc.users", service)
        registry.register_table("users", users_table)

        user_type = _edm_type(
            "ACP.User",
            properties={
                "Id": EdmProperty(name="Id", type=TypeRef("Edm.Int32"), nullable=False)
            },
        )
        registry.register_edm_schema(
            types={"ACP.User": user_type},
            entity_sets={"Users": EntitySet(name="Users", type=TypeRef("ACP.User"))},
        )
        registry.register_resource(_resource(edm_type_name="ACP.User"))

        self.assertEqual(registry.edm_services["svc.users"], service)
        self.assertIn("ACP.User", registry.resources)
        self.assertEqual(registry.schema_index["Users"], "ACP.User")
        self.assertIn("users", registry.tables)

    def test_freeze_idempotent_and_writable_guard(self) -> None:
        registry = AdminRegistry(strict_permission_decls=False)
        registry.freeze()
        registry.freeze()

        with self.assertRaisesRegex(RuntimeError, "frozen"):
            registry.register_table_spec(
                TableSpec(table_name="users", table_provider="pkg.mod:users")
            )

    def test_edm_service_registration_and_lookup_guards(self) -> None:
        registry = AdminRegistry()
        service_a = object()
        service_b = object()

        registry.register_edm_service("acp:svc", service_a)
        registry.register_edm_service("acp:svc", service_a)

        with self.assertRaisesRegex(ValueError, "already has a registered service"):
            registry.register_edm_service("acp:svc", service_b)

        with self.assertRaisesRegex(KeyError, "No service registered for key"):
            registry.get_edm_service("acp:missing")

    def test_resource_registration_guardrails_and_lookup(self) -> None:
        registry = AdminRegistry()

        missing_permissions_resource = AdminResource(
            namespace="acp",
            entity_set="Users",
            edm_type_name="ACP.User",
            perm_obj="user",
            service_key="svc.users",
            permissions=None,  # type: ignore[arg-type]
            behavior=AdminBehavior(rgql_enabled=False),
        )
        with self.assertRaisesRegex(ValueError, "missing permissions"):
            registry.register_resource(missing_permissions_resource)

        with self.assertRaisesRegex(
            ValueError, "permissions.permission_object is empty"
        ):
            registry.register_resource(
                _resource(permissions=_permissions(permission_object=""))
            )

        registry.register_resource(_resource())

        with self.assertRaisesRegex(ValueError, "Duplicate AdminResource entity_set"):
            registry.register_resource(_resource(entity_set="users"))

        with self.assertRaisesRegex(KeyError, "Unknown entity_set"):
            registry.get_resource("Missing")
        with self.assertRaisesRegex(KeyError, "Unknown edm_type_name"):
            registry.get_resource_by_type("ACP.Missing")

    def test_runtime_binding_spec_duplicate_guards(self) -> None:
        registry = AdminRegistry()

        registry.register_table_spec(
            TableSpec(table_name="acp_user", table_provider="pkg.mod:User")
        )
        with self.assertRaisesRegex(ValueError, "Duplicate TableSpec"):
            registry.register_table_spec(
                TableSpec(table_name="acp_user", table_provider="pkg.mod:User2")
            )

        registry.register_edm_type_spec(
            EdmTypeSpec(edm_type_name="ACP.User", edm_provider="pkg.mod:user_type")
        )
        with self.assertRaisesRegex(ValueError, "Duplicate EdmTypeSpec"):
            registry.register_edm_type_spec(
                EdmTypeSpec(edm_type_name="ACP.User", edm_provider="pkg.mod:user_type2")
            )

        registry.register_service_spec(
            RelationalServiceSpec(
                service_key="svc.user",
                service_cls="pkg.mod:UserService",
                init_kwargs={},
            )
        )
        with self.assertRaisesRegex(ValueError, "Duplicate ServiceSpec"):
            registry.register_service_spec(
                RelationalServiceSpec(
                    service_key="svc.user",
                    service_cls="pkg.mod:UserService2",
                    init_kwargs={},
                )
            )

        self.assertEqual(len(registry.table_specs()), 1)
        self.assertEqual(len(registry.edm_type_specs()), 1)
        self.assertEqual(len(registry.service_specs()), 1)

    def test_table_and_schema_registration_guards(self) -> None:
        registry = AdminRegistry()
        table_a = Table(
            "users",
            MetaData(),
            Column("id", Integer, primary_key=True),
        )
        table_b = Table(
            "users_other",
            MetaData(),
            Column("id", Integer, primary_key=True),
        )
        registry.register_table("users", table_a)
        registry.register_table("users", table_a)

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register_table("users", table_b)

        with self.assertRaisesRegex(KeyError, "No table with name"):
            registry.get_table("missing")

        registry.register_edm_schema(
            types={"ACP.User": _edm_type("ACP.User")},
            entity_sets={"Users": EntitySet(name="Users", type=TypeRef("ACP.User"))},
        )

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register_edm_schema(
                types={"ACP.User": _edm_type("ACP.User")},
                entity_sets={},
            )
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register_edm_schema(
                types={"ACP.Other": _edm_type("ACP.Other")},
                entity_sets={
                    "Users": EntitySet(name="Users", type=TypeRef("ACP.Other"))
                },
            )

    def test_permission_role_and_system_flag_duplicate_guards(self) -> None:
        registry = AdminRegistry()

        registry.register_permission_object(PermissionObjectDef("acp", "user"))
        with self.assertRaisesRegex(
            ValueError, "PermissionObject .* already registered"
        ):
            registry.register_permission_object(PermissionObjectDef("ACP", "USER"))

        registry.register_permission_type(PermissionTypeDef("acp", "read"))
        with self.assertRaisesRegex(ValueError, "PermissionType .* already registered"):
            registry.register_permission_type(PermissionTypeDef("ACP", "READ"))

        registry.register_global_role(GlobalRoleDef("acp", "admin", "Admin"))
        with self.assertRaisesRegex(ValueError, "GlobalRole .* already registered"):
            registry.register_global_role(GlobalRoleDef("ACP", "ADMIN", "Admin Upper"))

        registry.register_tenant_role_template(
            TenantRoleTemplateDef("acp", "owner", "Owner")
        )
        with self.assertRaisesRegex(
            ValueError, "TenantRoleTemplate .* already registered"
        ):
            registry.register_tenant_role_template(
                TenantRoleTemplateDef("ACP", "OWNER", "Owner Upper")
            )

        registry.register_system_flag(SystemFlagDef("acp", "alpha", "flag"))
        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register_system_flag(SystemFlagDef("ACP", "ALPHA", "flag upper"))

    def test_default_grant_wrappers_and_seed_manifest_sorting(self) -> None:
        registry = AdminRegistry()
        registry.register_permission_object(PermissionObjectDef("billing", "invoice"))
        registry.register_permission_object(PermissionObjectDef("acp", "user"))
        for ptype in ("manage", "read", "create"):
            registry.register_permission_type(PermissionTypeDef("acp", ptype))

        registry.register_global_role(GlobalRoleDef("acp", "viewer", "Viewer"))
        registry.register_global_role(GlobalRoleDef("acp", "admin", "Admin"))
        registry.register_tenant_role_template(
            TenantRoleTemplateDef("acp", "owner", "Owner")
        )
        registry.register_tenant_role_template(
            TenantRoleTemplateDef("acp", "editor", "Editor")
        )

        registry.register_default_global_grants(
            [
                DefaultGlobalGrant(
                    global_role="ACP:VIEWER",
                    permission_object="BILLING:INVOICE",
                    permission_type="ACP:READ",
                    permitted=True,
                ),
                DefaultGlobalGrant(
                    global_role="ACP:ADMIN",
                    permission_object="ACP:USER",
                    permission_type="ACP:MANAGE",
                    permitted=False,
                ),
            ]
        )
        registry.register_default_tenant_grants(
            [
                DefaultTenantTemplateGrant(
                    tenant_role_template="ACP:OWNER",
                    permission_object="ACP:USER",
                    permission_type="ACP:CREATE",
                    permitted=True,
                ),
                DefaultTenantTemplateGrant(
                    tenant_role_template="ACP:EDITOR",
                    permission_object="BILLING:INVOICE",
                    permission_type="ACP:READ",
                    permitted=True,
                ),
            ]
        )

        registry.register_system_flag(SystemFlagDef("acp", "zeta", "Z"))
        registry.register_system_flag(SystemFlagDef("acp", "alpha", "A"))

        manifest = registry.build_seed_manifest()

        self.assertEqual(
            [item.key for item in manifest.permission_objects],
            ["acp:user", "billing:invoice"],
        )
        self.assertEqual(
            [item.key for item in manifest.permission_types],
            ["acp:create", "acp:manage", "acp:read"],
        )
        self.assertEqual(
            [item.key for item in manifest.global_roles],
            ["acp:admin", "acp:viewer"],
        )
        self.assertEqual(
            [item.key for item in manifest.tenant_role_templates],
            ["acp:editor", "acp:owner"],
        )
        self.assertEqual(
            [grant.global_role for grant in manifest.default_global_grants],
            ["acp:admin", "acp:viewer"],
        )
        self.assertEqual(
            [grant.tenant_role_template for grant in manifest.default_tenant_grants],
            ["acp:editor", "acp:owner"],
        )
        self.assertEqual(
            [flag.key for flag in manifest.system_flags],
            ["acp:alpha", "acp:zeta"],
        )

    def test_freeze_strict_false_skips_permission_decl_checks(self) -> None:
        registry = AdminRegistry(strict_permission_decls=False)
        registry.register_resource(
            _resource(
                permissions=_permissions(
                    permission_object="acp:unknown-object",
                    read="acp:read-unknown",
                    create="acp:create-unknown",
                    update="acp:update-unknown",
                    delete="acp:delete-unknown",
                    manage="acp:manage-unknown",
                ),
                capabilities=AdminCapabilities(
                    actions={"approve": {"perm": "acp:not-registered"}}
                ),
                behavior=AdminBehavior(rgql_enabled=False),
            )
        )
        registry.register_default_global_grant(
            DefaultGlobalGrant(
                global_role="acp:missing-role",
                permission_object="acp:missing-object",
                permission_type="acp:missing-type",
                permitted=True,
            )
        )
        registry.register_default_tenant_grant(
            DefaultTenantTemplateGrant(
                tenant_role_template="acp:missing-template",
                permission_object="acp:missing-object",
                permission_type="acp:missing-type",
                permitted=True,
            )
        )

        registry.freeze()
        self.assertTrue(registry._frozen)

    def test_freeze_collects_permission_and_action_shape_errors(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)

        invalid_resource = _resource(
            namespace=" ",
            entity_set="Users",
            edm_type_name=" ",
            service_key=" ",
            permissions=_permissions(
                permission_object="badkey",
                read="badkey",
                create="",
                update="acp:update",
                delete="acp:delete",
                manage="acp:manage",
            ),
            capabilities=AdminCapabilities(
                actions={
                    "not_dict": "bad-spec",  # type: ignore[dict-item]
                    "empty_perm": {},
                    "invalid_perm": {"perm": "bad"},
                    "unknown_perm": {"perm": "acp:not-registered"},
                }
            ),
            behavior=AdminBehavior(rgql_enabled=False),
        )
        unknown_resource = _resource(
            entity_set=" ",
            permissions=_permissions(
                permission_object="acp:unknown-object",
                read="acp:unknown-read",
                create="acp:unknown-create",
                update="acp:unknown-update",
                delete="acp:unknown-delete",
                manage="acp:unknown-manage",
            ),
            behavior=AdminBehavior(rgql_enabled=False),
        )

        registry._resources.extend([invalid_resource, unknown_resource])

        with self.assertRaisesRegex(RuntimeError, "AdminRegistry validation failed"):
            registry.freeze()

    def test_freeze_soft_delete_and_rgql_validation_errors(self) -> None:
        registry = AdminRegistry(strict_permission_decls=False)
        registry.register_edm_schema(
            types={
                "ACP.NonTitle": _edm_type(
                    "ACP.NonTitle",
                    properties={
                        "deletedAt": EdmProperty(
                            name="deletedAt",
                            type=TypeRef("Edm.DateTimeOffset"),
                            nullable=True,
                        )
                    },
                ),
                "ACP.MissingProp": _edm_type(
                    "ACP.MissingProp",
                    properties={
                        "Id": EdmProperty(
                            name="Id",
                            type=TypeRef("Edm.Int32"),
                            nullable=False,
                        )
                    },
                ),
                "ACP.BadTs": _edm_type(
                    "ACP.BadTs",
                    properties={
                        "DeletedAt": EdmProperty(
                            name="DeletedAt",
                            type=TypeRef("Edm.String"),
                            nullable=False,
                        )
                    },
                ),
                "ACP.Flag": _edm_type(
                    "ACP.Flag",
                    properties={
                        "IsDeleted": EdmProperty(
                            name="IsDeleted",
                            type=TypeRef("Edm.String"),
                            nullable=False,
                        )
                    },
                ),
                "ACP.Source": _edm_type(
                    "ACP.Source",
                    nav_properties={
                        "UnknownTarget": EdmNavigationProperty(
                            name="UnknownTarget",
                            target_type=TypeRef("ACP.NoSuchTarget"),
                            source_fk="TargetId",
                        ),
                        "Children": EdmNavigationProperty(
                            name="Children",
                            target_type=TypeRef("ACP.Child", is_collection=True),
                            target_fk="",
                        ),
                        "Profile": EdmNavigationProperty(
                            name="Profile",
                            target_type=TypeRef("ACP.Profile"),
                            source_fk="",
                        ),
                    },
                ),
                "ACP.Child": _edm_type("ACP.Child"),
                "ACP.Profile": _edm_type("ACP.Profile"),
            },
            entity_sets={},
        )

        registry.register_resource(
            _resource(entity_set="NoPolicy", behavior=_BehaviorWithoutSoftDelete())
        )
        registry.register_resource(
            _resource(
                entity_set="NoneBad",
                edm_type_name="ACP.NonTitle",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.NONE,
                        column="DeletedAt",
                        allow_restore=True,
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="TsEmptyColumn",
                edm_type_name="ACP.NonTitle",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="",
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="TsNonTitle",
                edm_type_name="ACP.NonTitle",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="deletedAt",
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="TsUnknownType",
                edm_type_name="ACP.UnknownType",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="DeletedAt",
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="TsMissingProp",
                edm_type_name="ACP.MissingProp",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="DeletedAt",
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="TsBadProperty",
                edm_type_name="ACP.BadTs",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="DeletedAt",
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="FlagBadProperty",
                edm_type_name="ACP.Flag",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.FLAG,
                        column="IsDeleted",
                        deleted_value=None,
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="RgqlMissingType",
                edm_type_name="ACP.NotInSchema",
                behavior=AdminBehavior(rgql_enabled=True),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="RgqlNav",
                edm_type_name="ACP.Source",
                behavior=AdminBehavior(rgql_enabled=True),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "AdminRegistry validation failed"):
            registry.freeze()

    def test_freeze_soft_delete_additional_non_error_paths(self) -> None:
        registry = AdminRegistry(strict_permission_decls=False)
        registry.register_edm_schema(
            types={
                "ACP.FlagOk": _edm_type(
                    "ACP.FlagOk",
                    properties={
                        "IsDeleted": EdmProperty(
                            name="IsDeleted",
                            type=TypeRef("Edm.Boolean"),
                            nullable=False,
                        )
                    },
                )
            },
            entity_sets={},
        )

        registry.register_resource(
            _resource(
                entity_set="SeedUnknownType",
                edm_type_name="ACP.SeedingOnly",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.TIMESTAMP,
                        column="DeletedAt",
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="FlagSoftDeleteOk",
                edm_type_name="ACP.FlagOk",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode=SoftDeleteMode.FLAG,
                        column="IsDeleted",
                        deleted_value=True,
                    ),
                    rgql_enabled=False,
                ),
            )
        )
        registry.register_resource(
            _resource(
                entity_set="UnknownSoftDeleteMode",
                edm_type_name="ACP.FlagOk",
                behavior=AdminBehavior(
                    soft_delete=SoftDeletePolicy(
                        mode="custom",  # type: ignore[arg-type]
                        column="IsDeleted",
                        deleted_value=True,
                    ),
                    rgql_enabled=False,
                ),
            )
        )

        registry.freeze(seeding=True)
        self.assertTrue(registry._frozen)  # pylint: disable=protected-access

    def test_freeze_validates_grants_and_declared_roles(self) -> None:
        registry = AdminRegistry(strict_permission_decls=True)
        registry.register_global_role(GlobalRoleDef("acp", "admin", "Admin"))
        registry.register_tenant_role_template(
            TenantRoleTemplateDef("acp", "owner", "Owner")
        )

        # Freeze-time strict validation has branches for malformed grant keys.
        # register_default_*_grant normalizes eagerly, so malformed values are
        # injected directly here to exercise freeze's error collection.
        registry._default_global_grants.extend(
            [
                DefaultGlobalGrant(
                    global_role="acp:admin",
                    permission_object="bad",
                    permission_type="bad",
                    permitted=True,
                ),
                DefaultGlobalGrant(
                    global_role="acp:missing-role",
                    permission_object="acp:missing-object",
                    permission_type="acp:missing-type",
                    permitted=True,
                ),
            ]
        )
        registry._default_tenant_grants.extend(
            [
                DefaultTenantTemplateGrant(
                    tenant_role_template="acp:owner",
                    permission_object="bad",
                    permission_type="bad",
                    permitted=True,
                ),
                DefaultTenantTemplateGrant(
                    tenant_role_template="acp:missing-template",
                    permission_object="acp:missing-object",
                    permission_type="acp:missing-type",
                    permitted=True,
                ),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "AdminRegistry validation failed"):
            registry.freeze()


if __name__ == "__main__":
    unittest.main()
