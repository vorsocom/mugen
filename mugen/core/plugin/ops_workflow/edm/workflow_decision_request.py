"""Provides the workflow decision request EDM type definition."""

__all__ = ["workflow_decision_request_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

workflow_decision_request_type = EdmType(
    name="OPSWORKFLOW.WorkflowDecisionRequest",
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
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "TemplateKey": EdmProperty(
            "TemplateKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "RequesterActorJson": EdmProperty(
            "RequesterActorJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "AssignedToJson": EdmProperty(
            "AssignedToJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "OptionsJson": EdmProperty(
            "OptionsJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ContextJson": EdmProperty(
            "ContextJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "WorkflowInstanceId": EdmProperty(
            "WorkflowInstanceId",
            TypeRef("Edm.Guid"),
        ),
        "WorkflowTaskId": EdmProperty(
            "WorkflowTaskId",
            TypeRef("Edm.Guid"),
        ),
        "DueAt": EdmProperty("DueAt", TypeRef("Edm.DateTimeOffset")),
        "ResolvedAt": EdmProperty("ResolvedAt", TypeRef("Edm.DateTimeOffset")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowDecisionRequests",
)
