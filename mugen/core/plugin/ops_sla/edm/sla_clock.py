"""Provides the sla clock EDM type definition."""

__all__ = ["sla_clock_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_clock_type = EdmType(
    name="OPSSLA.SlaClock",
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
        "PolicyId": EdmProperty("PolicyId", TypeRef("Edm.Guid")),
        "CalendarId": EdmProperty("CalendarId", TypeRef("Edm.Guid")),
        "TargetId": EdmProperty("TargetId", TypeRef("Edm.Guid")),
        "ClockDefinitionId": EdmProperty("ClockDefinitionId", TypeRef("Edm.Guid")),
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "TrackedNamespace": EdmProperty(
            "TrackedNamespace", TypeRef("Edm.String"), nullable=False
        ),
        "TrackedId": EdmProperty("TrackedId", TypeRef("Edm.Guid")),
        "TrackedRef": EdmProperty("TrackedRef", TypeRef("Edm.String")),
        "Metric": EdmProperty("Metric", TypeRef("Edm.String"), nullable=False),
        "Priority": EdmProperty("Priority", TypeRef("Edm.String")),
        "Severity": EdmProperty("Severity", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "StartedAt": EdmProperty("StartedAt", TypeRef("Edm.DateTimeOffset")),
        "LastStartedAt": EdmProperty("LastStartedAt", TypeRef("Edm.DateTimeOffset")),
        "PausedAt": EdmProperty("PausedAt", TypeRef("Edm.DateTimeOffset")),
        "StoppedAt": EdmProperty("StoppedAt", TypeRef("Edm.DateTimeOffset")),
        "BreachedAt": EdmProperty("BreachedAt", TypeRef("Edm.DateTimeOffset")),
        "ElapsedSeconds": EdmProperty(
            "ElapsedSeconds", TypeRef("Edm.Int64"), nullable=False
        ),
        "DeadlineAt": EdmProperty("DeadlineAt", TypeRef("Edm.DateTimeOffset")),
        "IsBreached": EdmProperty("IsBreached", TypeRef("Edm.Boolean"), nullable=False),
        "BreachCount": EdmProperty("BreachCount", TypeRef("Edm.Int64"), nullable=False),
        "WarnedOffsetsJson": EdmProperty(
            "WarnedOffsetsJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "LastActorUserId": EdmProperty("LastActorUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsSlaClocks",
)
