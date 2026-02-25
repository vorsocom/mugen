"""Provides the sla clock-event EDM type definition."""

__all__ = ["sla_clock_event_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_clock_event_type = EdmType(
    name="OPSSLA.SlaClockEvent",
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
        "ClockDefinitionId": EdmProperty("ClockDefinitionId", TypeRef("Edm.Guid")),
        "EventType": EdmProperty("EventType", TypeRef("Edm.String"), nullable=False),
        "WarnedOffsetSeconds": EdmProperty(
            "WarnedOffsetSeconds",
            TypeRef("Edm.Int64"),
        ),
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "PayloadJson": EdmProperty(
            "PayloadJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsSlaClockEvents",
)
