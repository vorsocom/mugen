"""Provides the invoice line EDM type definition."""

__all__ = ["invoice_line_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

invoice_line_type = EdmType(
    name="BILLING.InvoiceLine",
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
        "InvoiceId": EdmProperty("InvoiceId", TypeRef("Edm.Guid"), nullable=False),
        "PriceId": EdmProperty("PriceId", TypeRef("Edm.Guid")),
        "TaxCodeId": EdmProperty("TaxCodeId", TypeRef("Edm.Guid")),
        "TaxRateId": EdmProperty("TaxRateId", TypeRef("Edm.Guid")),
        "Description": EdmProperty(
            "Description",
            TypeRef("Edm.String"),
            sortable=False,
        ),
        "Quantity": EdmProperty("Quantity", TypeRef("Edm.Int64"), nullable=False),
        "UnitAmount": EdmProperty("UnitAmount", TypeRef("Edm.Int64")),
        "Amount": EdmProperty("Amount", TypeRef("Edm.Int64"), nullable=False),
        "PeriodStart": EdmProperty("PeriodStart", TypeRef("Edm.DateTimeOffset")),
        "PeriodEnd": EdmProperty("PeriodEnd", TypeRef("Edm.DateTimeOffset")),
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
        "Invoice": EdmNavigationProperty(
            "Invoice",
            target_type=TypeRef("BILLING.Invoice"),
            source_fk="InvoiceId",
        ),
        "Price": EdmNavigationProperty(
            "Price",
            target_type=TypeRef("BILLING.Price"),
            source_fk="PriceId",
        ),
        "TaxCode": EdmNavigationProperty(
            "TaxCode", target_type=TypeRef("BILLING.TaxCode"), source_fk="TaxCodeId"
        ),
        "TaxRate": EdmNavigationProperty(
            "TaxRate", target_type=TypeRef("BILLING.TaxRate"), source_fk="TaxRateId"
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingInvoiceLines",
)
