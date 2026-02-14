"""Provides the vendor scorecard EDM type definition."""

__all__ = ["vendor_scorecard_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_scorecard_type = EdmType(
    name="OPSVPN.VendorScorecard",
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
        "VendorId": EdmProperty("VendorId", TypeRef("Edm.Guid"), nullable=False),
        "PeriodStart": EdmProperty(
            "PeriodStart", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "PeriodEnd": EdmProperty(
            "PeriodEnd", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "TimeToQuoteScore": EdmProperty("TimeToQuoteScore", TypeRef("Edm.Int64")),
        "CompletionRateScore": EdmProperty("CompletionRateScore", TypeRef("Edm.Int64")),
        "ComplaintRateScore": EdmProperty("ComplaintRateScore", TypeRef("Edm.Int64")),
        "ResponseSlaScore": EdmProperty("ResponseSlaScore", TypeRef("Edm.Int64")),
        "OverallScore": EdmProperty("OverallScore", TypeRef("Edm.Int64")),
        "EventCount": EdmProperty("EventCount", TypeRef("Edm.Int64"), nullable=False),
        "IsRoutable": EdmProperty("IsRoutable", TypeRef("Edm.Boolean"), nullable=False),
        "StatusFlags": EdmProperty(
            "StatusFlags",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ComputedAt": EdmProperty(
            "ComputedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "Vendor": EdmNavigationProperty(
            "Vendor",
            target_type=TypeRef("OPSVPN.Vendor"),
            source_fk="VendorId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsVpnVendorScorecards",
)
