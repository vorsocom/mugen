"""Provides an EdmType for the GlobalRoleMembership declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

global_role_membership_type = EdmType(
    name="ACP.GlobalRoleMembership",
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
        "GlobalRoleId": EdmProperty(
            "GlobalRoleId",
            TypeRef("Edm.Guid"),
        ),
        # UserScopedMixin.
        "UserId": EdmProperty(
            "UserId",
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
        "User": EdmNavigationProperty(
            "User",
            target_type=TypeRef(
                "ACP.User",
                is_collection=False,
            ),
            source_fk="UserId",
        ),
    },
    key_properties=("GlobalRoleId", "UserId"),
    entity_set_name="GlobalRoleMemberships",
)
