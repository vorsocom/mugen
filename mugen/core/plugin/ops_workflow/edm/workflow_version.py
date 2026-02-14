"""Provides the workflow version EDM type definition."""

__all__ = ["workflow_version_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

workflow_version_type = EdmType(
    name="OPSWORKFLOW.WorkflowVersion",
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
        "VersionNumber": EdmProperty(
            "VersionNumber",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "IsDefault": EdmProperty("IsDefault", TypeRef("Edm.Boolean"), nullable=False),
        "PublishedAt": EdmProperty("PublishedAt", TypeRef("Edm.DateTimeOffset")),
        "PublishedByUserId": EdmProperty("PublishedByUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "WorkflowStates": EdmNavigationProperty(
            "WorkflowStates",
            target_type=TypeRef("OPSWORKFLOW.WorkflowState", is_collection=True),
            target_fk="WorkflowVersionId",
        ),
        "WorkflowTransitions": EdmNavigationProperty(
            "WorkflowTransitions",
            target_type=TypeRef("OPSWORKFLOW.WorkflowTransition", is_collection=True),
            target_fk="WorkflowVersionId",
        ),
        "WorkflowInstances": EdmNavigationProperty(
            "WorkflowInstances",
            target_type=TypeRef("OPSWORKFLOW.WorkflowInstance", is_collection=True),
            target_fk="WorkflowVersionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowVersions",
)
