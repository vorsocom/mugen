"""Provides the report snapshot EDM type definition."""

__all__ = ["report_snapshot_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

report_snapshot_type = EdmType(
    name="OPSREPORTING.ReportSnapshot",
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
        "ReportDefinitionId": EdmProperty("ReportDefinitionId", TypeRef("Edm.Guid")),
        "MetricCodes": EdmProperty(
            "MetricCodes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "WindowStart": EdmProperty("WindowStart", TypeRef("Edm.DateTimeOffset")),
        "WindowEnd": EdmProperty("WindowEnd", TypeRef("Edm.DateTimeOffset")),
        "ScopeKey": EdmProperty("ScopeKey", TypeRef("Edm.String"), nullable=False),
        "SummaryJson": EdmProperty(
            "SummaryJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "GeneratedAt": EdmProperty("GeneratedAt", TypeRef("Edm.DateTimeOffset")),
        "PublishedAt": EdmProperty("PublishedAt", TypeRef("Edm.DateTimeOffset")),
        "ArchivedAt": EdmProperty("ArchivedAt", TypeRef("Edm.DateTimeOffset")),
        "GeneratedByUserId": EdmProperty("GeneratedByUserId", TypeRef("Edm.Guid")),
        "PublishedByUserId": EdmProperty("PublishedByUserId", TypeRef("Edm.Guid")),
        "ArchivedByUserId": EdmProperty("ArchivedByUserId", TypeRef("Edm.Guid")),
        "Note": EdmProperty("Note", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsReportingReportSnapshots",
)
