"""Provides the delegation grant EDM type definition."""

__all__ = ["delegation_grant_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

delegation_grant_type = EdmType(
    name="OPSGOVERNANCE.DelegationGrant",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "PrincipalUserId": EdmProperty(
            "PrincipalUserId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "DelegateUserId": EdmProperty(
            "DelegateUserId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "Scope": EdmProperty("Scope", TypeRef("Edm.String"), nullable=False),
        "Purpose": EdmProperty("Purpose", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "EffectiveFrom": EdmProperty(
            "EffectiveFrom",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "ExpiresAt": EdmProperty("ExpiresAt", TypeRef("Edm.DateTimeOffset")),
        "SourceGrantId": EdmProperty("SourceGrantId", TypeRef("Edm.Guid")),
        "RevokedAt": EdmProperty("RevokedAt", TypeRef("Edm.DateTimeOffset")),
        "RevokedByUserId": EdmProperty("RevokedByUserId", TypeRef("Edm.Guid")),
        "RevocationReason": EdmProperty("RevocationReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsDelegationGrants",
)
