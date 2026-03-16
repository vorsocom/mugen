"""Provides the usage event EDM type definition."""

__all__ = ["usage_event_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

usage_event_type = EdmType(
    name="BILLING.UsageEvent",
    kind="entity",
    properties={
        "Id": EdmProperty("Id", TypeRef("Edm.Guid"), nullable=False),
        "CreatedAt": EdmProperty(
            "CreatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "UpdatedAt": EdmProperty(
            "UpdatedAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "RowVersion": EdmProperty("RowVersion", TypeRef("Edm.Int64"), nullable=False),
        "TenantId": EdmProperty("TenantId", TypeRef("Edm.Guid"), nullable=False),
        "AccountId": EdmProperty("AccountId", TypeRef("Edm.Guid"), nullable=False),
        "SubscriptionId": EdmProperty("SubscriptionId", TypeRef("Edm.Guid")),
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid")),
        "MeterCode": EdmProperty("MeterCode", TypeRef("Edm.String"), nullable=False),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Quantity": EdmProperty("Quantity", TypeRef("Edm.Int64"), nullable=False),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
    },
    nav_properties={
        "Tenant": EdmNavigationProperty(
            "Tenant",
            target_type=TypeRef("ACP.Tenant"),
            source_fk="TenantId",
        ),
        "Account": EdmNavigationProperty(
            "Account",
            target_type=TypeRef("BILLING.Account"),
            source_fk="AccountId",
        ),
        "Subscription": EdmNavigationProperty(
            "Subscription",
            target_type=TypeRef("BILLING.Subscription"),
            source_fk="SubscriptionId",
        ),
        "Price": EdmNavigationProperty(
            "Price",
            target_type=TypeRef("BILLING.Price"),
            source_fk="PriceId",
        ),
        "UsageAllocations": EdmNavigationProperty(
            "UsageAllocations",
            target_type=TypeRef("BILLING.UsageAllocation", is_collection=True),
            target_fk="UsageEventId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingUsageEvents",
)
