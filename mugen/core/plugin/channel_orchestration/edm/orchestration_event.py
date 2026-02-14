"""Provides the orchestration event EDM type definition."""

__all__ = ["orchestration_event_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


orchestration_event_type = EdmType(
    name="CHANNELORCH.OrchestrationEvent",
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
        "ConversationStateId": EdmProperty("ConversationStateId", TypeRef("Edm.Guid")),
        "ChannelProfileId": EdmProperty("ChannelProfileId", TypeRef("Edm.Guid")),
        "SenderKey": EdmProperty("SenderKey", TypeRef("Edm.String")),
        "EventType": EdmProperty("EventType", TypeRef("Edm.String"), nullable=False),
        "Decision": EdmProperty("Decision", TypeRef("Edm.String")),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
        "Payload": EdmProperty(
            "Payload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Source": EdmProperty("Source", TypeRef("Edm.String")),
    },
    key_properties=("Id",),
    entity_set_name="OrchestrationEvents",
)
