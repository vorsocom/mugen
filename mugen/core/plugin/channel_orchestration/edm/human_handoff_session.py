"""Provides the human handoff session EDM type definition."""

__all__ = ["human_handoff_session_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


human_handoff_session_type = EdmType(
    name="CHANNELORCH.HumanHandoffSession",
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
        "ScopeKey": EdmProperty("ScopeKey", TypeRef("Edm.String"), nullable=False),
        "Platform": EdmProperty("Platform", TypeRef("Edm.String"), nullable=False),
        "ChannelId": EdmProperty("ChannelId", TypeRef("Edm.String")),
        "RoomId": EdmProperty("RoomId", TypeRef("Edm.String")),
        "SenderId": EdmProperty("SenderId", TypeRef("Edm.String")),
        "ConversationId": EdmProperty("ConversationId", TypeRef("Edm.String")),
        "ClientProfileId": EdmProperty("ClientProfileId", TypeRef("Edm.Guid")),
        "ServiceRouteKey": EdmProperty("ServiceRouteKey", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "OwnerUserId": EdmProperty("OwnerUserId", TypeRef("Edm.Guid")),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
        "ActivatedAt": EdmProperty(
            "ActivatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "DeactivatedAt": EdmProperty(
            "DeactivatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "DeactivatedByUserId": EdmProperty(
            "DeactivatedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "DeactivationReason": EdmProperty(
            "DeactivationReason",
            TypeRef("Edm.String"),
        ),
        "LastHumanReplyAt": EdmProperty(
            "LastHumanReplyAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LastUserMessageAt": EdmProperty(
            "LastUserMessageAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LastTranscriptSequenceNo": EdmProperty(
            "LastTranscriptSequenceNo",
            TypeRef("Edm.Int64"),
        ),
        "LastDeliveryStatus": EdmProperty(
            "LastDeliveryStatus",
            TypeRef("Edm.String"),
        ),
        "LastDeliveryError": EdmProperty(
            "LastDeliveryError",
            TypeRef("Edm.String"),
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="HumanHandoffSessions",
)
