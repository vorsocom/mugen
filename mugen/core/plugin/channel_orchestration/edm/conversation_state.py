"""Provides the conversation state EDM type definition."""

__all__ = ["conversation_state_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


conversation_state_type = EdmType(
    name="CHANNELORCH.ConversationState",
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
        "PolicyId": EdmProperty("PolicyId", TypeRef("Edm.Guid")),
        "SenderKey": EdmProperty("SenderKey", TypeRef("Edm.String"), nullable=False),
        "ExternalConversationRef": EdmProperty(
            "ExternalConversationRef",
            TypeRef("Edm.String"),
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "RouteKey": EdmProperty("RouteKey", TypeRef("Edm.String")),
        "AssignedQueueName": EdmProperty("AssignedQueueName", TypeRef("Edm.String")),
        "AssignedOwnerUserId": EdmProperty("AssignedOwnerUserId", TypeRef("Edm.Guid")),
        "AssignedServiceKey": EdmProperty("AssignedServiceKey", TypeRef("Edm.String")),
        "LastIntakeRuleId": EdmProperty("LastIntakeRuleId", TypeRef("Edm.Guid")),
        "LastIntakeResult": EdmProperty("LastIntakeResult", TypeRef("Edm.String")),
        "EscalationLevel": EdmProperty(
            "EscalationLevel",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "IsEscalated": EdmProperty(
            "IsEscalated",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "IsThrottled": EdmProperty(
            "IsThrottled",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "ThrottledUntil": EdmProperty("ThrottledUntil", TypeRef("Edm.DateTimeOffset")),
        "WindowStartedAt": EdmProperty(
            "WindowStartedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "WindowMessageCount": EdmProperty(
            "WindowMessageCount",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "FallbackMode": EdmProperty("FallbackMode", TypeRef("Edm.String")),
        "FallbackTarget": EdmProperty("FallbackTarget", TypeRef("Edm.String")),
        "FallbackReason": EdmProperty("FallbackReason", TypeRef("Edm.String")),
        "IsFallbackActive": EdmProperty(
            "IsFallbackActive",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "LastActivityAt": EdmProperty("LastActivityAt", TypeRef("Edm.DateTimeOffset")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="ConversationStates",
)
