"""Provides an EdmType for the GlobalPermissionEntry declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

global_permission_entry_type = EdmType(
    name="ACP.GlobalPermissionEntry",
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
        # GlobalRoleScopedMixin.
        "GlobalRoleId": EdmProperty(
            "GlobalRoleId",
            TypeRef("Edm.Guid"),
        ),
        # GlobalPermissionEntry.
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
        "GlobalRole": EdmNavigationProperty(
            "GlobalRole",
            target_type=TypeRef(
                "ACP.GlobalRole",
                is_collection=False,
            ),
            source_fk="GlobalRoleId",
        ),
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
    },
    key_properties="Id",
    entity_set_name="GlobalPermissionEntries",
)
