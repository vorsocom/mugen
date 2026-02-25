"""Provides the sla escalation-run EDM type definition."""

__all__ = ["sla_escalation_run_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_escalation_run_type = EdmType(
    name="OPSSLA.SlaEscalationRun",
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
        "EscalationPolicyId": EdmProperty(
            "EscalationPolicyId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "ClockId": EdmProperty("ClockId", TypeRef("Edm.Guid")),
        "ClockEventId": EdmProperty("ClockEventId", TypeRef("Edm.Guid")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "TriggerEventJson": EdmProperty(
            "TriggerEventJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ResultsJson": EdmProperty(
            "ResultsJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "ExecutedAt": EdmProperty(
            "ExecutedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "ExecutedByUserId": EdmProperty("ExecutedByUserId", TypeRef("Edm.Guid")),
    },
    key_properties=("Id",),
    entity_set_name="OpsSlaEscalationRuns",
)
