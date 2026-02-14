"""Provides the ledger entry EDM type definition."""

__all__ = ["ledger_entry_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

ledger_entry_type = EdmType(
    name="BILLING.LedgerEntry",
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
        "PaymentId": EdmProperty("PaymentId", TypeRef("Edm.Guid")),
        "Direction": EdmProperty("Direction", TypeRef("Edm.String"), nullable=False),
        "Currency": EdmProperty("Currency", TypeRef("Edm.String"), nullable=False),
        "Amount": EdmProperty("Amount", TypeRef("Edm.Int64"), nullable=False),
        "OccurredAt": EdmProperty(
            "OccurredAt", TypeRef("Edm.DateTimeOffset"), nullable=False
        ),
        "Description": EdmProperty(
            "Description",
            TypeRef("Edm.String"),
            sortable=False,
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
        "Invoice": EdmNavigationProperty(
            "Invoice",
            target_type=TypeRef("BILLING.Invoice"),
            source_fk="InvoiceId",
        ),
        "Payment": EdmNavigationProperty(
            "Payment",
            target_type=TypeRef("BILLING.Payment"),
            source_fk="PaymentId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingLedgerEntries",
)
