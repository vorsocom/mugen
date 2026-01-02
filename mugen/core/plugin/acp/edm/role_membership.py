"""Provides an EdmType for the RoleMembership declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

role_membership_type = EdmType(
    name="ACP.RoleMembership",
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
        # UserScopedMixin.
        "UserId": EdmProperty(
            "UserId",
            TypeRef("Edm.Guid"),
        ),
    },
    nav_properties={
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
        "User": EdmNavigationProperty(
            "User",
            target_type=TypeRef(
                "ACP.User",
                is_collection=False,
            ),
            source_fk="UserId",
        ),
    },
    key_properties=("TenantId", "RoleId", "UserId"),
    entity_set_name="RoleMemberships",
)
