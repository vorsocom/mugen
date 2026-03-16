"""Provides an EdmType for the TenantInvitation declarative model."""

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

tenant_invitation_type = EdmType(
    name="ACP.TenantInvitation",
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
        # TenantInvitation.
        "Email": EdmProperty(
            "Email",
            TypeRef("Edm.String"),
        ),
        "InvitedByUserId": EdmProperty(
            "InvitedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "TokenHash": EdmProperty(
            "TokenHash",
            TypeRef("Edm.String"),
        ),
        "ExpiresAt": EdmProperty(
            "ExpiresAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "AcceptedAt": EdmProperty(
            "AcceptedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "AcceptedByUserId": EdmProperty(
            "AcceptedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "RevokedAt": EdmProperty(
            "RevokedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "RevokedByUserId": EdmProperty(
            "RevokedByUserId",
            TypeRef("Edm.Guid"),
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
    },
    key_properties=("TenantId", "Id"),
    entity_set_name="TenantInvitations",
)
