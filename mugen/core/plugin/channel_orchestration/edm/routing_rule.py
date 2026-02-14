"""Provides the routing rule EDM type definition."""

__all__ = ["routing_rule_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


routing_rule_type = EdmType(
    name="CHANNELORCH.RoutingRule",
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
        "RouteKey": EdmProperty("RouteKey", TypeRef("Edm.String"), nullable=False),
        "TargetQueueName": EdmProperty("TargetQueueName", TypeRef("Edm.String")),
        "OwnerUserId": EdmProperty("OwnerUserId", TypeRef("Edm.Guid")),
        "TargetServiceKey": EdmProperty("TargetServiceKey", TypeRef("Edm.String")),
        "TargetNamespace": EdmProperty("TargetNamespace", TypeRef("Edm.String")),
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
    entity_set_name="RoutingRules",
)
