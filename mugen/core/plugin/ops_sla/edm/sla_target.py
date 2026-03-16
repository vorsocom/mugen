"""Provides the sla target EDM type definition."""

__all__ = ["sla_target_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_target_type = EdmType(
    name="OPSSLA.SlaTarget",
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
        "PolicyId": EdmProperty("PolicyId", TypeRef("Edm.Guid"), nullable=False),
        "Metric": EdmProperty("Metric", TypeRef("Edm.String"), nullable=False),
        "Priority": EdmProperty("Priority", TypeRef("Edm.String")),
        "Severity": EdmProperty("Severity", TypeRef("Edm.String")),
        "TargetMinutes": EdmProperty(
            "TargetMinutes", TypeRef("Edm.Int64"), nullable=False
        ),
        "WarnBeforeMinutes": EdmProperty(
            "WarnBeforeMinutes", TypeRef("Edm.Int64"), nullable=False
        ),
        "AutoBreach": EdmProperty("AutoBreach", TypeRef("Edm.Boolean"), nullable=False),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsSlaTargets",
)
