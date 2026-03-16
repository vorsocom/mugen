"""Provides the intake rule EDM type definition."""

__all__ = ["intake_rule_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


intake_rule_type = EdmType(
    name="CHANNELORCH.IntakeRule",
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
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "MatchKind": EdmProperty("MatchKind", TypeRef("Edm.String"), nullable=False),
        "MatchValue": EdmProperty("MatchValue", TypeRef("Edm.String"), nullable=False),
        "RouteKey": EdmProperty("RouteKey", TypeRef("Edm.String")),
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
    entity_set_name="IntakeRules",
)
