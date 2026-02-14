"""Provides the metric definition EDM type definition."""

__all__ = ["metric_definition_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

metric_definition_type = EdmType(
    name="OPSREPORTING.MetricDefinition",
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
        "FormulaType": EdmProperty(
            "FormulaType",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "SourceTable": EdmProperty(
            "SourceTable",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "SourceTimeColumn": EdmProperty("SourceTimeColumn", TypeRef("Edm.String")),
        "SourceValueColumn": EdmProperty("SourceValueColumn", TypeRef("Edm.String")),
        "ScopeColumn": EdmProperty("ScopeColumn", TypeRef("Edm.String")),
        "SourceFilter": EdmProperty(
            "SourceFilter",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
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
    entity_set_name="OpsReportingMetricDefinitions",
)
