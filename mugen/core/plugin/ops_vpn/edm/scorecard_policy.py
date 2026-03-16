"""Provides the scorecard policy EDM type definition."""

__all__ = ["scorecard_policy_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

scorecard_policy_type = EdmType(
    name="OPSVPN.ScorecardPolicy",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "DisplayName": EdmProperty("DisplayName", TypeRef("Edm.String")),
        "TimeToQuoteWeight": EdmProperty(
            "TimeToQuoteWeight", TypeRef("Edm.Int64"), nullable=False
        ),
        "CompletionRateWeight": EdmProperty(
            "CompletionRateWeight", TypeRef("Edm.Int64"), nullable=False
        ),
        "ComplaintRateWeight": EdmProperty(
            "ComplaintRateWeight", TypeRef("Edm.Int64"), nullable=False
        ),
        "ResponseSlaWeight": EdmProperty(
            "ResponseSlaWeight", TypeRef("Edm.Int64"), nullable=False
        ),
        "MinSampleSize": EdmProperty(
            "MinSampleSize", TypeRef("Edm.Int64"), nullable=False
        ),
        "MinimumOverallScore": EdmProperty(
            "MinimumOverallScore", TypeRef("Edm.Int64"), nullable=False
        ),
        "RequireAllMetrics": EdmProperty(
            "RequireAllMetrics", TypeRef("Edm.Boolean"), nullable=False
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={},
    key_properties=("Id",),
    entity_set_name="OpsVpnScorecardPolicies",
)
