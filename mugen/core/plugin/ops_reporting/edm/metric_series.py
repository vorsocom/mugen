"""Provides the metric series EDM type definition."""

__all__ = ["metric_series_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

metric_series_type = EdmType(
    name="OPSREPORTING.MetricSeries",
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
        "MetricDefinitionId": EdmProperty(
            "MetricDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "BucketStart": EdmProperty(
            "BucketStart",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "BucketEnd": EdmProperty(
            "BucketEnd",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "ScopeKey": EdmProperty("ScopeKey", TypeRef("Edm.String"), nullable=False),
        "ValueNumeric": EdmProperty(
            "ValueNumeric",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "SourceCount": EdmProperty("SourceCount", TypeRef("Edm.Int64"), nullable=False),
        "ComputedAt": EdmProperty(
            "ComputedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "AggregationKey": EdmProperty(
            "AggregationKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsReportingMetricSeries",
)
