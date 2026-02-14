"""Provides the meter definition EDM type definition."""

__all__ = ["meter_definition_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

meter_definition_type = EdmType(
    name="OPSMETERING.MeterDefinition",
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
        "Unit": EdmProperty("Unit", TypeRef("Edm.String"), nullable=False),
        "AggregationMode": EdmProperty(
            "AggregationMode",
            TypeRef("Edm.String"),
            nullable=False,
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
    entity_set_name="OpsMeterDefinitions",
)
