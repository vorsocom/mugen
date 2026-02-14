"""Provides the orchestration policy EDM type definition."""

__all__ = ["orchestration_policy_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef


orchestration_policy_type = EdmType(
    name="CHANNELORCH.OrchestrationPolicy",
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
        "HoursMode": EdmProperty("HoursMode", TypeRef("Edm.String"), nullable=False),
        "EscalationMode": EdmProperty(
            "EscalationMode",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "FallbackPolicy": EdmProperty(
            "FallbackPolicy",
            TypeRef("Edm.String"),
            nullable=False,
        ),
        "FallbackTarget": EdmProperty("FallbackTarget", TypeRef("Edm.String")),
        "EscalationTarget": EdmProperty("EscalationTarget", TypeRef("Edm.String")),
        "EscalationAfterSeconds": EdmProperty(
            "EscalationAfterSeconds",
            TypeRef("Edm.Int64"),
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
    entity_set_name="OrchestrationPolicies",
)
