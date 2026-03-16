"""Provides the entitlement bucket EDM type definition."""

__all__ = ["entitlement_bucket_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

entitlement_bucket_type = EdmType(
    name="BILLING.EntitlementBucket",
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
        "PeriodStart": EdmProperty(
            "PeriodStart",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "PeriodEnd": EdmProperty(
            "PeriodEnd",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "IncludedQuantity": EdmProperty(
            "IncludedQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "ConsumedQuantity": EdmProperty(
            "ConsumedQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
        "RolloverQuantity": EdmProperty(
            "RolloverQuantity",
            TypeRef("Edm.Int64"),
            nullable=False,
        ),
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
            target_fk="EntitlementBucketId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingEntitlementBuckets",
)
