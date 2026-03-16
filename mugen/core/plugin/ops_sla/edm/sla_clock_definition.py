"""Provides the sla clock-definition EDM type definition."""

__all__ = ["sla_clock_definition_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_clock_definition_type = EdmType(
    name="OPSSLA.SlaClockDefinition",
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
        "Metric": EdmProperty("Metric", TypeRef("Edm.String"), nullable=False),
        "TargetMinutes": EdmProperty(
            "TargetMinutes",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "WarnOffsetsJson": EdmProperty(
            "WarnOffsetsJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsSlaClockDefinitions",
)
