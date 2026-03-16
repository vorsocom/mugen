"""Provides the vendor performance event EDM type definition."""

__all__ = ["vendor_performance_event_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

vendor_performance_event_type = EdmType(
    name="OPSVPN.VendorPerformanceEvent",
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
        "MetricType": EdmProperty("MetricType", TypeRef("Edm.String"), nullable=False),
        "ObservedAt": EdmProperty(
            "ObservedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "MetricValue": EdmProperty("MetricValue", TypeRef("Edm.Int64")),
        "MetricNumerator": EdmProperty("MetricNumerator", TypeRef("Edm.Int64")),
        "MetricDenominator": EdmProperty("MetricDenominator", TypeRef("Edm.Int64")),
        "NormalizedScore": EdmProperty("NormalizedScore", TypeRef("Edm.Int64")),
        "SampleSize": EdmProperty("SampleSize", TypeRef("Edm.Int64"), nullable=False),
        "Unit": EdmProperty("Unit", TypeRef("Edm.String")),
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
    entity_set_name="OpsVpnVendorPerformanceEvents",
)
