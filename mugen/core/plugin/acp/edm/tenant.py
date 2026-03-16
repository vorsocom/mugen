"""Provides an EdmType for the Tenant declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

tenant_type = EdmType(
    name="ACP.Tenant",
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
        # SoftDeleteMixin.
        "DeletedAt": EdmProperty(
            "DeletedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "DeletedByUserId": EdmProperty(
            "DeletedByUserId",
            TypeRef("Edm.Guid"),
        ),
        # Tenant.
        "Name": EdmProperty(
            "Name",
            TypeRef("Edm.String"),
        ),
        "Slug": EdmProperty(
            "Slug",
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
            target_fk="TenantId",
        ),
        "Roles": EdmNavigationProperty(
            "Roles",
            target_type=TypeRef(
                "ACP.Role",
                is_collection=True,
            ),
            target_fk="TenantId",
        ),
        "RoleMemberships": EdmNavigationProperty(
            "RoleMemberships",
            target_type=TypeRef(
                "ACP.RoleMembership",
                is_collection=True,
            ),
            target_fk="TenantId",
        ),
        "TenantDomains": EdmNavigationProperty(
            "TenantDomains",
            target_type=TypeRef(
                "ACP.TenantDomain",
                is_collection=True,
            ),
            target_fk="TenantId",
        ),
        "TenantInvitations": EdmNavigationProperty(
            "TenantInvitations",
            target_type=TypeRef(
                "ACP.TenantInvitation",
                is_collection=True,
            ),
            target_fk="TenantId",
        ),
        "TenantMemberships": EdmNavigationProperty(
            "TenantMemberships",
            target_type=TypeRef(
                "ACP.TenantMembership",
                is_collection=True,
            ),
            target_fk="TenantId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="Tenants",
)
