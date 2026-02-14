"""Provides the KPI threshold EDM type definition."""

__all__ = ["kpi_threshold_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

kpi_threshold_type = EdmType(
    name="OPSREPORTING.KpiThreshold",
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
        "ScopeKey": EdmProperty("ScopeKey", TypeRef("Edm.String"), nullable=False),
        "TargetValue": EdmProperty("TargetValue", TypeRef("Edm.Int64")),
        "WarnLow": EdmProperty("WarnLow", TypeRef("Edm.Int64")),
        "WarnHigh": EdmProperty("WarnHigh", TypeRef("Edm.Int64")),
        "CriticalLow": EdmProperty("CriticalLow", TypeRef("Edm.Int64")),
        "CriticalHigh": EdmProperty("CriticalHigh", TypeRef("Edm.Int64")),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsReportingKpiThresholds",
)
