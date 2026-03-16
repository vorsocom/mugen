"""Provides the blocklist entry EDM type definition."""

__all__ = ["blocklist_entry_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


blocklist_entry_type = EdmType(
    name="CHANNELORCH.BlocklistEntry",
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
        "ChannelProfileId": EdmProperty("ChannelProfileId", TypeRef("Edm.Guid")),
        "SenderKey": EdmProperty("SenderKey", TypeRef("Edm.String"), nullable=False),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
        "BlockedAt": EdmProperty(
            "BlockedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "BlockedByUserId": EdmProperty("BlockedByUserId", TypeRef("Edm.Guid")),
        "ExpiresAt": EdmProperty("ExpiresAt", TypeRef("Edm.DateTimeOffset")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "UnblockedAt": EdmProperty("UnblockedAt", TypeRef("Edm.DateTimeOffset")),
        "UnblockedByUserId": EdmProperty("UnblockedByUserId", TypeRef("Edm.Guid")),
        "UnblockReason": EdmProperty("UnblockReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="BlocklistEntries",
)
