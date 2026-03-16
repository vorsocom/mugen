"""Provides an EdmType for the GlobalRole declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

global_role_type = EdmType(
    name="ACP.GlobalRole",
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
        # GlobalRole.
        "Namespace": EdmProperty(
            "Namespace",
            TypeRef("Edm.String"),
        ),
        "Name": EdmProperty(
            "Name",
            TypeRef("Edm.String"),
        ),
        "DisplayName": EdmProperty(
            "DisplayName",
            TypeRef("Edm.String"),
        ),
    },
    nav_properties={
        "GlobalPermissionEntries": EdmNavigationProperty(
            "GlobalPermissionEntries",
            target_type=TypeRef(
                "ACP.GlobalPermissionEntry",
                is_collection=True,
            ),
            target_fk="GlobalRoleId",
        ),
        "GlobalRoleMemberships": EdmNavigationProperty(
            "GlobalRoleMemberships",
            target_type=TypeRef(
                "ACP.GlobalRoleMembership",
                is_collection=True,
            ),
            target_fk="GlobalRoleId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="GlobalRoles",
)
