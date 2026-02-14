"""Provides the workflow task EDM type definition."""

__all__ = ["workflow_task_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

workflow_task_type = EdmType(
    name="OPSWORKFLOW.WorkflowTask",
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
        "WorkflowTransitionId": EdmProperty(
            "WorkflowTransitionId",
            TypeRef("Edm.Guid"),
        ),
        "TaskKind": EdmProperty("TaskKind", TypeRef("Edm.String"), nullable=False),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "Title": EdmProperty("Title", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "AssigneeUserId": EdmProperty("AssigneeUserId", TypeRef("Edm.Guid")),
        "QueueName": EdmProperty("QueueName", TypeRef("Edm.String")),
        "AssignedByUserId": EdmProperty("AssignedByUserId", TypeRef("Edm.Guid")),
        "AssignedAt": EdmProperty("AssignedAt", TypeRef("Edm.DateTimeOffset")),
        "HandoffCount": EdmProperty(
            "HandoffCount",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "CompletedAt": EdmProperty("CompletedAt", TypeRef("Edm.DateTimeOffset")),
        "CancelledAt": EdmProperty("CancelledAt", TypeRef("Edm.DateTimeOffset")),
        "CompletedByUserId": EdmProperty("CompletedByUserId", TypeRef("Edm.Guid")),
        "Outcome": EdmProperty("Outcome", TypeRef("Edm.String")),
        "Payload": EdmProperty(
            "Payload",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowTasks",
)
