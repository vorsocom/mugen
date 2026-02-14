"""Provides the workflow instance EDM type definition."""

__all__ = ["workflow_instance_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

workflow_instance_type = EdmType(
    name="OPSWORKFLOW.WorkflowInstance",
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
        "WorkflowDefinitionId": EdmProperty(
            "WorkflowDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "WorkflowVersionId": EdmProperty(
            "WorkflowVersionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "CurrentStateId": EdmProperty("CurrentStateId", TypeRef("Edm.Guid")),
        "PendingTransitionId": EdmProperty("PendingTransitionId", TypeRef("Edm.Guid")),
        "PendingTaskId": EdmProperty("PendingTaskId", TypeRef("Edm.Guid")),
        "Title": EdmProperty("Title", TypeRef("Edm.String")),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "SubjectNamespace": EdmProperty("SubjectNamespace", TypeRef("Edm.String")),
        "SubjectId": EdmProperty("SubjectId", TypeRef("Edm.Guid")),
        "SubjectRef": EdmProperty("SubjectRef", TypeRef("Edm.String")),
        "StartedAt": EdmProperty("StartedAt", TypeRef("Edm.DateTimeOffset")),
        "CompletedAt": EdmProperty("CompletedAt", TypeRef("Edm.DateTimeOffset")),
        "CancelledAt": EdmProperty("CancelledAt", TypeRef("Edm.DateTimeOffset")),
        "LastActorUserId": EdmProperty("LastActorUserId", TypeRef("Edm.Guid")),
        "CancelReason": EdmProperty("CancelReason", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "WorkflowTasks": EdmNavigationProperty(
            "WorkflowTasks",
            target_type=TypeRef("OPSWORKFLOW.WorkflowTask", is_collection=True),
            target_fk="WorkflowInstanceId",
        ),
        "WorkflowEvents": EdmNavigationProperty(
            "WorkflowEvents",
            target_type=TypeRef("OPSWORKFLOW.WorkflowEvent", is_collection=True),
            target_fk="WorkflowInstanceId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowInstances",
)
