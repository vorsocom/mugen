"""Provides the sla breach event EDM type definition."""

__all__ = ["sla_breach_event_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_breach_event_type = EdmType(
    name="OPSSLA.SlaBreachEvent",
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
        "ClockId": EdmProperty("ClockId", TypeRef("Edm.Guid"), nullable=False),
        "EventType": EdmProperty("EventType", TypeRef("Edm.String"), nullable=False),
        "OccurredAt": EdmProperty(
            "OccurredAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "EscalationLevel": EdmProperty(
            "EscalationLevel", TypeRef("Edm.Int64"), nullable=False
        ),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
        "Note": EdmProperty("Note", TypeRef("Edm.String")),
        "Payload": EdmProperty(
            "Payload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsSlaBreachEvents",
)
