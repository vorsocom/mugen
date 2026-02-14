"""Provides the price EDM type definition."""

__all__ = ["price_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

price_type = EdmType(
    name="BILLING.Price",
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
        "ProductId": EdmProperty("ProductId", TypeRef("Edm.Guid"), nullable=False),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "PriceType": EdmProperty("PriceType", TypeRef("Edm.String"), nullable=False),
        "Currency": EdmProperty("Currency", TypeRef("Edm.String"), nullable=False),
        "UnitAmount": EdmProperty("UnitAmount", TypeRef("Edm.Int64")),
        "IntervalUnit": EdmProperty("IntervalUnit", TypeRef("Edm.String")),
        "IntervalCount": EdmProperty("IntervalCount", TypeRef("Edm.Int32")),
        "TrialPeriodDays": EdmProperty("TrialPeriodDays", TypeRef("Edm.Int32")),
        "UsageUnit": EdmProperty("UsageUnit", TypeRef("Edm.String")),
        "MeterCode": EdmProperty("MeterCode", TypeRef("Edm.String"), nullable=False),
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
        "Product": EdmNavigationProperty(
            "Product",
            target_type=TypeRef("BILLING.Product"),
            source_fk="ProductId",
        ),
        "Subscriptions": EdmNavigationProperty(
            "Subscriptions",
            target_type=TypeRef("BILLING.Subscription", is_collection=True),
            target_fk="PriceId",
        ),
        "InvoiceLines": EdmNavigationProperty(
            "InvoiceLines",
            target_type=TypeRef("BILLING.InvoiceLine", is_collection=True),
            target_fk="PriceId",
        ),
        "UsageEvents": EdmNavigationProperty(
            "UsageEvents",
            target_type=TypeRef("BILLING.UsageEvent", is_collection=True),
            target_fk="PriceId",
        ),
        "EntitlementBuckets": EdmNavigationProperty(
            "EntitlementBuckets",
            target_type=TypeRef("BILLING.EntitlementBucket", is_collection=True),
            target_fk="PriceId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingPrices",
)
