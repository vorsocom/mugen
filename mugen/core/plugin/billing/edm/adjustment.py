"""Provides the adjustment EDM type definition."""

__all__ = ["adjustment_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

adjustment_type = EdmType(
    name="BILLING.Adjustment",
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
        "CreditNoteId": EdmProperty("CreditNoteId", TypeRef("Edm.Guid")),
        "Kind": EdmProperty("Kind", TypeRef("Edm.String"), nullable=False),
        "Currency": EdmProperty("Currency", TypeRef("Edm.String"), nullable=False),
        "Amount": EdmProperty("Amount", TypeRef("Edm.Int64"), nullable=False),
        "OccurredAt": EdmProperty(
            "OccurredAt",
            TypeRef("Edm.DateTimeOffset"),
            nullable=False,
        ),
        "Reason": EdmProperty("Reason", TypeRef("Edm.String")),
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
        "CreditNote": EdmNavigationProperty(
            "CreditNote",
            target_type=TypeRef("BILLING.CreditNote"),
            source_fk="CreditNoteId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingAdjustments",
)
