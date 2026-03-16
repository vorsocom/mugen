"""Provides the workflow event EDM type definition."""

__all__ = ["workflow_event_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

workflow_event_type = EdmType(
    name="OPSWORKFLOW.WorkflowEvent",
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
        "WorkflowInstanceId": EdmProperty(
            "WorkflowInstanceId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "WorkflowTaskId": EdmProperty("WorkflowTaskId", TypeRef("Edm.Guid")),
        "EventSeq": EdmProperty("EventSeq", TypeRef("Edm.Int64")),
        "EventType": EdmProperty("EventType", TypeRef("Edm.String"), nullable=False),
        "FromStateId": EdmProperty("FromStateId", TypeRef("Edm.Guid")),
        "ToStateId": EdmProperty("ToStateId", TypeRef("Edm.Guid")),
        "ActorUserId": EdmProperty("ActorUserId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Note": EdmProperty("Note", TypeRef("Edm.String")),
        "Payload": EdmProperty(
            "Payload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowEvents",
)
