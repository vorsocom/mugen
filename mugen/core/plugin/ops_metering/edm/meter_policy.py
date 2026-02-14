"""Provides the meter policy EDM type definition."""

__all__ = ["meter_policy_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

meter_policy_type = EdmType(
    name="OPSMETERING.MeterPolicy",
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
        "MeterDefinitionId": EdmProperty(
            "MeterDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "CapMinutes": EdmProperty("CapMinutes", TypeRef("Edm.Int64")),
        "CapUnits": EdmProperty("CapUnits", TypeRef("Edm.Int64")),
        "CapTasks": EdmProperty("CapTasks", TypeRef("Edm.Int64")),
        "MultiplierBps": EdmProperty(
            "MultiplierBps",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "RoundingMode": EdmProperty(
            "RoundingMode",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "RoundingStep": EdmProperty(
            "RoundingStep",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "BillableWindowMinutes": EdmProperty(
            "BillableWindowMinutes",
            TypeRef("Edm.Int64"),
        ),
        "EffectiveFrom": EdmProperty("EffectiveFrom", TypeRef("Edm.DateTimeOffset")),
        "EffectiveTo": EdmProperty("EffectiveTo", TypeRef("Edm.DateTimeOffset")),
        "IsActive": EdmProperty("IsActive", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsMeterPolicies",
)
