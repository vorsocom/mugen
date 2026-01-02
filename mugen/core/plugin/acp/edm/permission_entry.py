"""Provides an EdmType for the PermissionEntry declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

permission_entry_type = EdmType(
    name="ACP.PermissionEntry",
    kind="entity",
    properties={
        # ModelBase.
        "Id": EdmProperty(
            "Id",
            TypeRef("Edm.Guid"),
        ),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "RowVersion": EdmProperty(
            "RowVersion",
            TypeRef("Edm.Int64"),
        ),
        # RoleScopedMixin.
        "RoleId": EdmProperty(
            "RoleId",
            TypeRef("Edm.Guid"),
        ),
        # TenantScopedMixin.
        "TenantId": EdmProperty(
            "TenantId",
            TypeRef("Edm.Guid"),
        ),
        # PermissionEntry.
        "Permitted": EdmProperty(
            "Permitted",
            TypeRef("Edm.Boolean"),
        ),
        "PermissionObjectId": EdmProperty(
            "PermissionObjectId",
            TypeRef("Edm.Guid"),
        ),
        "PermissionTypeId": EdmProperty(
            "PermissionTypeId",
            TypeRef("Edm.Guid"),
        ),
    },
    nav_properties={
        "PermissionObject": EdmNavigationProperty(
            "PermissionObject",
            target_type=TypeRef(
                "ACP.PermissionObject",
                is_collection=False,
            ),
            source_fk="PermissionObjectId",
        ),
        "PermissionType": EdmNavigationProperty(
            "PermissionType",
            target_type=TypeRef(
                "ACP.PermissionType",
                is_collection=False,
            ),
            source_fk="PermissionTypeId",
        ),
        "Role": EdmNavigationProperty(
            "Role",
            target_type=TypeRef(
                "ACP.Role",
                is_collection=False,
            ),
            source_fk="RoleId",
        ),
        "Tenant": EdmNavigationProperty(
            "Tenant",
            target_type=TypeRef(
                "ACP.Tenant",
                is_collection=False,
            ),
            source_fk="TenantId",
        ),
    },
    key_properties=("TenantId", "Id"),
    entity_set_name="PermissionEntries",
)
