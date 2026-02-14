"""Provides the invoice EDM type definition."""

__all__ = ["invoice_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

invoice_type = EdmType(
    name="BILLING.Invoice",
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
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "Number": EdmProperty("Number", TypeRef("Edm.String")),
        "Currency": EdmProperty("Currency", TypeRef("Edm.String"), nullable=False),
        "SubtotalAmount": EdmProperty(
            "SubtotalAmount", TypeRef("Edm.Int64"), nullable=False
        ),
        "TaxAmount": EdmProperty("TaxAmount", TypeRef("Edm.Int64"), nullable=False),
        "TotalAmount": EdmProperty("TotalAmount", TypeRef("Edm.Int64"), nullable=False),
        "AmountDue": EdmProperty("AmountDue", TypeRef("Edm.Int64"), nullable=False),
        "IssuedAt": EdmProperty("IssuedAt", TypeRef("Edm.DateTimeOffset")),
        "DueAt": EdmProperty("DueAt", TypeRef("Edm.DateTimeOffset")),
        "PaidAt": EdmProperty("PaidAt", TypeRef("Edm.DateTimeOffset")),
        "VoidedAt": EdmProperty("VoidedAt", TypeRef("Edm.DateTimeOffset")),
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
        "Subscription": EdmNavigationProperty(
            "Subscription",
            target_type=TypeRef("BILLING.Subscription"),
            source_fk="SubscriptionId",
        ),
        "Lines": EdmNavigationProperty(
            "Lines",
            target_type=TypeRef("BILLING.InvoiceLine", is_collection=True),
            target_fk="InvoiceId",
        ),
        "CreditNotes": EdmNavigationProperty(
            "CreditNotes",
            target_type=TypeRef("BILLING.CreditNote", is_collection=True),
            target_fk="InvoiceId",
        ),
        "Adjustments": EdmNavigationProperty(
            "Adjustments",
            target_type=TypeRef("BILLING.Adjustment", is_collection=True),
            target_fk="InvoiceId",
        ),
        "Payments": EdmNavigationProperty(
            "Payments",
            target_type=TypeRef("BILLING.Payment", is_collection=True),
            target_fk="InvoiceId",
        ),
        "Allocations": EdmNavigationProperty(
            "Allocations",
            target_type=TypeRef("BILLING.PaymentAllocation", is_collection=True),
            target_fk="InvoiceId",
        ),
        "LedgerEntries": EdmNavigationProperty(
            "LedgerEntries",
            target_type=TypeRef("BILLING.LedgerEntry", is_collection=True),
            target_fk="InvoiceId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingInvoices",
)
