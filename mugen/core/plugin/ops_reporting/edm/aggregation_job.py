"""Provides the aggregation job EDM type definition."""

__all__ = ["aggregation_job_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

aggregation_job_type = EdmType(
    name="OPSREPORTING.AggregationJob",
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
        "WindowStart": EdmProperty(
            "WindowStart",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "WindowEnd": EdmProperty(
            "WindowEnd",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "BucketMinutes": EdmProperty(
            "BucketMinutes",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "ScopeKey": EdmProperty("ScopeKey", TypeRef("Edm.String"), nullable=False),
        "IdempotencyKey": EdmProperty(
            "IdempotencyKey",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "StartedAt": EdmProperty("StartedAt", TypeRef("Edm.DateTimeOffset")),
        "FinishedAt": EdmProperty("FinishedAt", TypeRef("Edm.DateTimeOffset")),
        "LastRunAt": EdmProperty("LastRunAt", TypeRef("Edm.DateTimeOffset")),
        "ErrorMessage": EdmProperty("ErrorMessage", TypeRef("Edm.String")),
        "CreatedByUserId": EdmProperty("CreatedByUserId", TypeRef("Edm.Guid")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsReportingAggregationJobs",
)
