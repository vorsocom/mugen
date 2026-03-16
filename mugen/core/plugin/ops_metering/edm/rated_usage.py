"""Provides the rated usage EDM type definition."""

__all__ = ["rated_usage_type"]

from mugen.core.utility.rgql.model import EdmProperty, EdmType, TypeRef

rated_usage_type = EdmType(
    name="OPSMETERING.RatedUsage",
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
        "UsageRecordId": EdmProperty(
            "UsageRecordId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "MeterDefinitionId": EdmProperty(
            "MeterDefinitionId",
            TypeRef("Edm.Guid"),
            nullable=False,
        ),
        "MeterPolicyId": EdmProperty("MeterPolicyId", TypeRef("Edm.Guid")),
        "AccountId": EdmProperty("AccountId", TypeRef("Edm.Guid")),
        "SubscriptionId": EdmProperty("SubscriptionId", TypeRef("Edm.Guid")),
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid")),
        "MeterCode": EdmProperty("MeterCode", TypeRef("Edm.String"), nullable=False),
        "Unit": EdmProperty("Unit", TypeRef("Edm.String"), nullable=False),
        "MeasuredQuantity": EdmProperty(
            "MeasuredQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "CappedQuantity": EdmProperty(
            "CappedQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "MultiplierBps": EdmProperty(
            "MultiplierBps",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "BillableQuantity": EdmProperty(
            "BillableQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "RatedAt": EdmProperty(
            "RatedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "VoidedAt": EdmProperty("VoidedAt", TypeRef("Edm.DateTimeOffset")),
        "VoidReason": EdmProperty("VoidReason", TypeRef("Edm.String")),
        "BillingUsageEventId": EdmProperty("BillingUsageEventId", TypeRef("Edm.Guid")),
        "BillingExternalRef": EdmProperty(
            "BillingExternalRef",
            TypeRef("Edm.String"),
        ),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    key_properties=("Id",),
    entity_set_name="OpsRatedUsages",
)
