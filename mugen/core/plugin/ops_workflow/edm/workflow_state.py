"""Provides the workflow state EDM type definition."""

__all__ = ["workflow_state_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

workflow_state_type = EdmType(
    name="OPSWORKFLOW.WorkflowState",
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
        "WorkflowVersionId": EdmProperty(
            "WorkflowVersionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "Key": EdmProperty("Key", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "IsInitial": EdmProperty("IsInitial", TypeRef("Edm.Boolean"), nullable=False),
        "IsTerminal": EdmProperty("IsTerminal", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowStates",
)
