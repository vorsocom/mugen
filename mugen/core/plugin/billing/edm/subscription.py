"""Provides the subscription EDM type definition."""

__all__ = ["subscription_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

subscription_type = EdmType(
    name="BILLING.Subscription",
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
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid"), nullable=False),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "StartedAt": EdmProperty(
            "StartedAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "CurrentPeriodStart": EdmProperty(
            "CurrentPeriodStart",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "CurrentPeriodEnd": EdmProperty(
            "CurrentPeriodEnd",
            TypeRef("Edm.DateTimeOffset"),
        ),
        "CancelAt": EdmProperty("CancelAt", TypeRef("Edm.DateTimeOffset")),
        "CanceledAt": EdmProperty("CanceledAt", TypeRef("Edm.DateTimeOffset")),
        "EndedAt": EdmProperty("EndedAt", TypeRef("Edm.DateTimeOffset")),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "Attributes": EdmProperty(
            "Attributes",
            TypeRef("Edm.String"),
            filterable=False,
            sortable=False,
        ),
        "DeletedAt": EdmProperty("DeletedAt", TypeRef("Edm.DateTimeOffset")),
        "DeletedByUserId": EdmProperty("DeletedByUserId", TypeRef("Edm.Guid")),
    },
    nav_properties={
        "Tenant": EdmNavigationProperty(
            "Tenant",
            target_type=TypeRef("ACP.Tenant"),
            source_fk="TenantId",
        ),
        "DeletedByUser": EdmNavigationProperty(
            "DeletedByUser",
            target_type=TypeRef("ACP.User"),
            source_fk="DeletedByUserId",
        ),
        "Account": EdmNavigationProperty(
            "Account",
            target_type=TypeRef("BILLING.Account"),
            source_fk="AccountId",
        ),
        "Price": EdmNavigationProperty(
            "Price",
            target_type=TypeRef("BILLING.Price"),
            source_fk="PriceId",
        ),
        "Invoices": EdmNavigationProperty(
            "Invoices",
            target_type=TypeRef("BILLING.Invoice", is_collection=True),
            target_fk="SubscriptionId",
        ),
        "UsageEvents": EdmNavigationProperty(
            "UsageEvents",
            target_type=TypeRef("BILLING.UsageEvent", is_collection=True),
            target_fk="SubscriptionId",
        ),
        "BillingRuns": EdmNavigationProperty(
            "BillingRuns",
            target_type=TypeRef("BILLING.BillingRun", is_collection=True),
            target_fk="SubscriptionId",
        ),
        "EntitlementBuckets": EdmNavigationProperty(
            "EntitlementBuckets",
            target_type=TypeRef("BILLING.EntitlementBucket", is_collection=True),
            target_fk="SubscriptionId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingSubscriptions",
)
