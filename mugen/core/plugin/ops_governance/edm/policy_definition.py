"""Provides the policy definition EDM type definition."""

__all__ = ["policy_definition_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

policy_definition_type = EdmType(
    name="OPSGOVERNANCE.PolicyDefinition",
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
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "PolicyType": EdmProperty("PolicyType", TypeRef("Edm.String")),
        "RuleRef": EdmProperty("RuleRef", TypeRef("Edm.String")),
        "EvaluationMode": EdmProperty(
            "EvaluationMode",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Engine": EdmProperty("Engine", TypeRef("Edm.String"), nullable=False),
        "Version": EdmProperty("Version", TypeRef("Edm.Int64"), nullable=False),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "LastEvaluatedAt": EdmProperty(
            "LastEvaluatedAt",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "LastEvaluatedByUserId": EdmProperty(
            "LastEvaluatedByUserId",
            TypeRef("Edm.Guid"),
        ),
        "LastDecisionLogId": EdmProperty("LastDecisionLogId", TypeRef("Edm.Guid")),
        "DocumentJson": EdmProperty(
            "DocumentJson",
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
    entity_set_name="OpsPolicyDefinitions",
)
