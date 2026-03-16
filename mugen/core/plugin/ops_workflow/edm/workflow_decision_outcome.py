"""Provides the workflow decision outcome EDM type definition."""

__all__ = ["workflow_decision_outcome_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

workflow_decision_outcome_type = EdmType(
    name="OPSWORKFLOW.WorkflowDecisionOutcome",
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
        "DecisionRequestId": EdmProperty(
            "DecisionRequestId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "ResolverActorJson": EdmProperty(
            "ResolverActorJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "OutcomeJson": EdmProperty(
            "OutcomeJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "SignatureJson": EdmProperty(
            "SignatureJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsWorkflowDecisionOutcomes",
)
