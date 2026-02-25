"""Provides the sla escalation-policy EDM type definition."""

__all__ = ["sla_escalation_policy_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

sla_escalation_policy_type = EdmType(
    name="OPSSLA.SlaEscalationPolicy",
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
        "PolicyKey": EdmProperty("PolicyKey", TypeRef("Edm.String"), nullable=False),
        "Name": EdmProperty("Name", TypeRef("Edm.String"), nullable=False),
        "Description": EdmProperty("Description", TypeRef("Edm.String")),
        "Priority": EdmProperty("Priority", TypeRef("Edm.Int64"), nullable=False),
        "TriggersJson": EdmProperty(
            "TriggersJson",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "ActionsJson": EdmProperty(
            "ActionsJson",
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
    entity_set_name="OpsSlaEscalationPolicies",
)
