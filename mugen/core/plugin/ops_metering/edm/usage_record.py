"""Provides the usage record EDM type definition."""

__all__ = ["usage_record_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

usage_record_type = EdmType(
    name="OPSMETERING.UsageRecord",
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
        "MeterPolicyId": EdmProperty("MeterPolicyId", TypeRef("Edm.Guid")),
        "UsageSessionId": EdmProperty("UsageSessionId", TypeRef("Edm.Guid")),
        "RatedUsageId": EdmProperty("RatedUsageId", TypeRef("Edm.Guid")),
        "AccountId": EdmProperty("AccountId", TypeRef("Edm.Guid")),
        "SubscriptionId": EdmProperty("SubscriptionId", TypeRef("Edm.Guid")),
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid")),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "MeasuredMinutes": EdmProperty(
            "MeasuredMinutes",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "MeasuredUnits": EdmProperty(
            "MeasuredUnits",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "MeasuredTasks": EdmProperty(
            "MeasuredTasks",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "RatedAt": EdmProperty("RatedAt", TypeRef("Edm.DateTimeOffset")),
        "VoidedAt": EdmProperty("VoidedAt", TypeRef("Edm.DateTimeOffset")),
        "VoidReason": EdmProperty("VoidReason", TypeRef("Edm.String")),
        "IdempotencyKey": EdmProperty("IdempotencyKey", TypeRef("Edm.String")),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsUsageRecords",
)
