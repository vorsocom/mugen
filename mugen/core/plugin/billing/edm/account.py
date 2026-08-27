"""Provides the account EDM type definition."""

__all__ = ["account_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

account_type = EdmType(
    name="BILLING.Account",
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
        "CurrencyDefinitionId": EdmProperty(
            "CurrencyDefinitionId", TypeRef("Edm.Guid")
        ),
        "TaxCodeId": EdmProperty("TaxCodeId", TypeRef("Edm.Guid")),
        "PaymentTermId": EdmProperty("PaymentTermId", TypeRef("Edm.Guid")),
        "InvoiceTemplateId": EdmProperty("InvoiceTemplateId", TypeRef("Edm.Guid")),
        "DiscountDefinitionId": EdmProperty(
            "DiscountDefinitionId", TypeRef("Edm.Guid")
        ),
        "Code": EdmProperty("Code", TypeRef("Edm.String"), nullable=False),
        "DisplayName": EdmProperty(
            "DisplayName", TypeRef("Edm.String"), nullable=False
        ),
        "Email": EdmProperty("Email", TypeRef("Edm.String")),
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
        "CurrencyDefinition": EdmNavigationProperty(
            "CurrencyDefinition",
            target_type=TypeRef("BILLING.CurrencyDefinition"),
            source_fk="CurrencyDefinitionId",
        ),
        "TaxCode": EdmNavigationProperty(
            "TaxCode", target_type=TypeRef("BILLING.TaxCode"), source_fk="TaxCodeId"
        ),
        "PaymentTerm": EdmNavigationProperty(
            "PaymentTerm",
            target_type=TypeRef("BILLING.PaymentTerm"),
            source_fk="PaymentTermId",
        ),
        "InvoiceTemplate": EdmNavigationProperty(
            "InvoiceTemplate",
            target_type=TypeRef("BILLING.InvoiceTemplate"),
            source_fk="InvoiceTemplateId",
        ),
        "DiscountDefinition": EdmNavigationProperty(
            "DiscountDefinition",
            target_type=TypeRef("BILLING.DiscountDefinition"),
            source_fk="DiscountDefinitionId",
        ),
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
        "Subscriptions": EdmNavigationProperty(
            "Subscriptions",
            target_type=TypeRef("BILLING.Subscription", is_collection=True),
            target_fk="AccountId",
        ),
        "BillingRuns": EdmNavigationProperty(
            "BillingRuns",
            target_type=TypeRef("BILLING.BillingRun", is_collection=True),
            target_fk="AccountId",
        ),
        "Invoices": EdmNavigationProperty(
            "Invoices",
            target_type=TypeRef("BILLING.Invoice", is_collection=True),
            target_fk="AccountId",
        ),
        "CreditNotes": EdmNavigationProperty(
            "CreditNotes",
            target_type=TypeRef("BILLING.CreditNote", is_collection=True),
            target_fk="AccountId",
        ),
        "Adjustments": EdmNavigationProperty(
            "Adjustments",
            target_type=TypeRef("BILLING.Adjustment", is_collection=True),
            target_fk="AccountId",
        ),
        "Payments": EdmNavigationProperty(
            "Payments",
            target_type=TypeRef("BILLING.Payment", is_collection=True),
            target_fk="AccountId",
        ),
        "UsageEvents": EdmNavigationProperty(
            "UsageEvents",
            target_type=TypeRef("BILLING.UsageEvent", is_collection=True),
            target_fk="AccountId",
        ),
        "LedgerEntries": EdmNavigationProperty(
            "LedgerEntries",
            target_type=TypeRef("BILLING.LedgerEntry", is_collection=True),
            target_fk="AccountId",
        ),
        "EntitlementBuckets": EdmNavigationProperty(
            "EntitlementBuckets",
            target_type=TypeRef("BILLING.EntitlementBucket", is_collection=True),
            target_fk="AccountId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingAccounts",
)
