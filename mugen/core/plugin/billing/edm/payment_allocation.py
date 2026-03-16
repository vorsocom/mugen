"""Provides the payment allocation EDM type definition."""

__all__ = ["payment_allocation_type"]

from mugen.core.utility.rgql.model import (
    EdmNavigationProperty,
    EdmProperty,
    EdmType,
    TypeRef,
)

payment_allocation_type = EdmType(
    name="BILLING.PaymentAllocation",
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
        "PaymentId": EdmProperty("PaymentId", TypeRef("Edm.Guid"), nullable=False),
        "InvoiceId": EdmProperty("InvoiceId", TypeRef("Edm.Guid"), nullable=False),
        "Amount": EdmProperty("Amount", TypeRef("Edm.Int64"), nullable=False),
        "AllocatedAt": EdmProperty(
            "AllocatedAt",
            TypeRef("Edm.DateTimeOffset"),
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
        "Payment": EdmNavigationProperty(
            "Payment",
            target_type=TypeRef("BILLING.Payment"),
            source_fk="PaymentId",
        ),
        "Invoice": EdmNavigationProperty(
            "Invoice",
            target_type=TypeRef("BILLING.Invoice"),
            source_fk="InvoiceId",
        ),
    },
    key_properties=("Id",),
    entity_set_name="BillingPaymentAllocations",
)
