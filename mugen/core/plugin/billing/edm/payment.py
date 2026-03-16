"""Provides the payment EDM type definition."""

__all__ = ["payment_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

payment_type = EdmType(
    name="BILLING.Payment",
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
        "InvoiceId": EdmProperty("InvoiceId", TypeRef("Edm.Guid")),
        "Status": EdmProperty("Status", TypeRef("Edm.String"), nullable=False),
        "Currency": EdmProperty("Currency", TypeRef("Edm.String"), nullable=False),
        "Amount": EdmProperty("Amount", TypeRef("Edm.Int64"), nullable=False),
        "Provider": EdmProperty("Provider", TypeRef("Edm.String")),
        "ExternalRef": EdmProperty("ExternalRef", TypeRef("Edm.String")),
        "ReceivedAt": EdmProperty("ReceivedAt", TypeRef("Edm.DateTimeOffset")),
        "FailedAt": EdmProperty("FailedAt", TypeRef("Edm.DateTimeOffset")),
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
        "Invoice": EdmNavigationProperty(
            "Invoice",
            target_type=TypeRef("BILLING.Invoice"),
            source_fk="InvoiceId",
        ),
        "LedgerEntries": EdmNavigationProperty(
            "LedgerEntries",
            target_type=TypeRef("BILLING.LedgerEntry", is_collection=True),
            target_fk="PaymentId",
        ),
        "Allocations": EdmNavigationProperty(
            "Allocations",
            target_type=TypeRef("BILLING.PaymentAllocation", is_collection=True),
            target_fk="PaymentId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingPayments",
)
