"""Provides an EdmType for the KeyRef declarative model."""

__all__ = ["key_ref_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

key_ref_type = EdmType(
    name="ACP.KeyRef",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty("CreatedAt", TypeRef("Edm.DateTimeOffset")),
        "UpdatedAt": EdmProperty("UpdatedAt", TypeRef("Edm.DateTimeOffset")),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64")),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid")),
        "Purpose": EdmProperty("Purpose", TypeRef("Edm.String"), nullable=False),
        "KeyId": EdmProperty("KeyId", TypeRef("Edm.String"), nullable=False),
        "Provider": EdmProperty("Provider", TypeRef("Edm.String"), nullable=False),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "ActivatedAt": EdmProperty(
            "ActivatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "RetiredAt": EdmProperty("RetiredAt", TypeRef("Edm.DateTimeOffset")),
        "RetiredByUserId": EdmProperty("RetiredByUserId", TypeRef("Edm.Guid")),
        "RetiredReason": EdmProperty("RetiredReason", TypeRef("Edm.String")),
        "DestroyedAt": EdmProperty("DestroyedAt", TypeRef("Edm.DateTimeOffset")),
        "DestroyedByUserId": EdmProperty(
            "DestroyedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "DestroyReason": EdmProperty("DestroyReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="KeyRefs",
)
