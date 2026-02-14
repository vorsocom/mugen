"""Provides the workflow definition EDM type definition."""

__all__ = ["workflow_definition_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

workflow_definition_type = EdmType(
    name="OPSWORKFLOW.WorkflowDefinition",
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
        "Key": EdmProperty("Key", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DeletedAt": EdmProperty("DeletedAt", TypeRef("Edm.DateTimeOffset")),
        "DeletedByUserId": EdmProperty("DeletedByUserId", TypeRef("Edm.Guid")),
    },
    nav_properties={
        "WorkflowVersions": EdmNavigationProperty(
            "WorkflowVersions",
            target_type=TypeRef("OPSWORKFLOW.WorkflowVersion", is_collection=True),
            target_fk="WorkflowDefinitionId",
        ),
        "WorkflowInstances": EdmNavigationProperty(
            "WorkflowInstances",
            target_type=TypeRef("OPSWORKFLOW.WorkflowInstance", is_collection=True),
            target_fk="WorkflowDefinitionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowDefinitions",
)
