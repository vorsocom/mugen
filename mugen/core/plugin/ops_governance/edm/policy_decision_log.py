"""Provides the policy decision log EDM type definition."""

__all__ = ["policy_decision_log_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

policy_decision_log_type = EdmType(
    name="OPSGOVERNANCE.PolicyDecisionLog",
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
        "PolicyDefinitionId": EdmProperty(
            "PolicyDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "TraceId": EdmProperty("TraceId", TypeRef("Edm.String")),
        "PolicyKey": EdmProperty("PolicyKey", TypeRef("Edm.String")),
        "PolicyVersion": EdmProperty("PolicyVersion", TypeRef("Edm.Int64")),
        "SubjectNamespace": EdmProperty(
            "SubjectNamespace",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "SubjectId": EdmProperty("SubjectId", TypeRef("Edm.Guid")),
        "SubjectRef": EdmProperty("SubjectRef", TypeRef("Edm.String")),
        "Decision": EdmProperty("Decision", TypeRef("Edm.String"), nullable=False),
        "Outcome": EdmProperty("Outcome", TypeRef("Edm.String"), nullable=False),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
        "EvaluatedAt": EdmProperty(
            "EvaluatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "EvaluatorUserId": EdmProperty("EvaluatorUserId", TypeRef("Edm.Guid")),
        "RequestContext": EdmProperty(
            "RequestContext",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ActorJson": EdmProperty(
            "ActorJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "InputJson": EdmProperty(
            "InputJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DecisionJson": EdmProperty(
            "DecisionJson",
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
        "RetentionUntil": EdmProperty(
            "RetentionUntil",
            TypeRef("Edm.DateTimeOffset"),
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsPolicyDecisionLogs",
)
