"""Provides the credit note EDM type definition."""

__all__ = ["credit_note_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

credit_note_type = EdmType(
    name="BILLING.CreditNote",
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
        "Number": EdmProperty("Number", TypeRef("Edm.String")),
        "Currency": EdmProperty("Currency", TypeRef("Edm.String"), nullable=False),
        "TotalAmount": EdmProperty("TotalAmount", TypeRef("Edm.Int64"), nullable=False),
        "IssuedAt": EdmProperty("IssuedAt", TypeRef("Edm.DateTimeOffset")),
        "VoidedAt": EdmProperty("VoidedAt", TypeRef("Edm.DateTimeOffset")),
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
        "Adjustments": EdmNavigationProperty(
            "Adjustments",
            target_type=TypeRef("BILLING.Adjustment", is_collection=True),
            target_fk="CreditNoteId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingCreditNotes",
)
