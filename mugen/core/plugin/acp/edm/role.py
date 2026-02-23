"""Provides an EdmType for the Role declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

role_type = EdmType(
    name="ACP.Role",
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
        # Role.
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
        "Status": EdmProperty(
            "Status",
            TypeRef("Edm.String"),
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
        "PermissionEntries": EdmNavigationProperty(
            "PermissionEntries",
            target_type=TypeRef(
                "ACP.PermissionEntry",
                is_collection=True,
            ),
            target_fk="RoleId",
        ),
        "RoleMemberships": EdmNavigationProperty(
            "RoleMemberships",
            target_type=TypeRef(
                "ACP.RoleMembership",
                is_collection=True,
            ),
            target_fk="RoleId",
        ),
    },
    key_properties=("TenantId", "Id"),
    entity_set_name="Roles",
)
