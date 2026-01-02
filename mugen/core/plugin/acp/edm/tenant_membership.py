"""Provides an EdmType for the TenantMembership declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

tenant_membership_type = EdmType(
    name="ACP.TenantMembership",
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
        # TenantMembership.
        "RoleInTenant": EdmProperty(
            "RoleInTenant",
            TypeRef("Edm.String"),
        ),
        "Status": EdmProperty(
            "Status",
            TypeRef("Edm.String"),
        ),
        "JoinedAt": EdmProperty(
            "JoinedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
    },
    nav_properties={
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
    key_properties=("TenantId", "Id"),
    entity_set_name="TenantMemberships",
)
