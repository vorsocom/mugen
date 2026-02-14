"""Provides the throttle rule EDM type definition."""

__all__ = ["throttle_rule_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


throttle_rule_type = EdmType(
    name="CHANNELORCH.ThrottleRule",
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
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "SenderScope": EdmProperty(
            "SenderScope",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "WindowSeconds": EdmProperty(
            "WindowSeconds",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "MaxMessages": EdmProperty("MaxMessages", TypeRef("Edm.Int64"), nullable=False),
        "BlockOnViolation": EdmProperty(
            "BlockOnViolation",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "BlockDurationSeconds": EdmProperty(
            "BlockDurationSeconds",
            TypeRef("Edm.Int64"),
        ),
        "Priority": EdmProperty("Priority", TypeRef("Edm.Int64"), nullable=False),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ThrottleRules",
)
