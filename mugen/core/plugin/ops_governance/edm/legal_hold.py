"""Provides the legal hold EDM type definition."""

__all__ = ["legal_hold_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

legal_hold_type = EdmType(
    name="OPSGOVERNANCE.LegalHold",
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
        "RetentionClassId": EdmProperty("RetentionClassId", TypeRef("Edm.Guid")),
        "ResourceType": EdmProperty(
            "ResourceType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "ResourceId": EdmProperty("ResourceId", TypeRef("Edm.Guid"), nullable=False),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String"), nullable=False),
        "HoldUntil": EdmProperty("HoldUntil", TypeRef("Edm.DateTimeOffset")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "PlacedAt": EdmProperty(
            "PlacedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "PlacedByUserId": EdmProperty("PlacedByUserId", TypeRef("Edm.Guid")),
        "ReleasedAt": EdmProperty("ReleasedAt", TypeRef("Edm.DateTimeOffset")),
        "ReleasedByUserId": EdmProperty("ReleasedByUserId", TypeRef("Edm.Guid")),
        "ReleaseReason": EdmProperty("ReleaseReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsLegalHolds",
)
