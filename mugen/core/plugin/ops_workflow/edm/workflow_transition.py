"""Provides the workflow transition EDM type definition."""

__all__ = ["workflow_transition_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

workflow_transition_type = EdmType(
    name="OPSWORKFLOW.WorkflowTransition",
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
        "FromStateId": EdmProperty("FromStateId", TypeRef("Edm.Guid"), nullable=False),
        "ToStateId": EdmProperty("ToStateId", TypeRef("Edm.Guid"), nullable=False),
        "RequiresApproval": EdmProperty(
            "RequiresApproval",
            TypeRef("Edm.Boolean"),
            nullable=False,
        ),
        "AutoAssignUserId": EdmProperty("AutoAssignUserId", TypeRef("Edm.Guid")),
        "AutoAssignQueue": EdmProperty("AutoAssignQueue", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowTransitions",
)
