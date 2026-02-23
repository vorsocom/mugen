"""Provides an EdmType for the PermissionType declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

permission_type_type = EdmType(
    name="ACP.PermissionType",
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
        # PermissionType.
        "Namespace": EdmProperty(
            "Namespace",
            TypeRef("Edm.String"),
        ),
        "Name": EdmProperty(
            "Name",
            TypeRef("Edm.String"),
        ),
        "Status": EdmProperty(
            "Status",
            TypeRef("Edm.String"),
        ),
    },
    nav_properties={
        "PermissionEntries": EdmNavigationProperty(
            "PermissionEntries",
            target_type=TypeRef(
                "ACP.PermissionEntry",
                is_collection=True,
            ),
            target_fk="PermissionTypeId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="PermissionTypes",
)
