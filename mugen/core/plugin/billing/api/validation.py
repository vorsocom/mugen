"""Validation schemas used by billing ACP CRUD resources."""

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation,
    build_update_validation,
)

__all__ = [
    "BillingAccountCreateValidation",
    "BillingAccountUpdateValidation",
    "BillingAdjustmentCreateValidation",
    "BillingAdjustmentUpdateValidation",
    "BillingCreditNoteCreateValidation",
    "BillingCreditNoteUpdateValidation",
    "BillingEntitlementBucketCreateValidation",
    "BillingEntitlementBucketUpdateValidation",
    "BillingInvoiceCreateValidation",
    "BillingInvoiceLineCreateValidation",
    "BillingInvoiceLineUpdateValidation",
    "BillingInvoiceUpdateValidation",
    "BillingLedgerEntryCreateValidation",
    "BillingPaymentAllocationCreateValidation",
    "BillingPaymentCreateValidation",
    "BillingPaymentUpdateValidation",
    "BillingPriceCreateValidation",
    "BillingPriceUpdateValidation",
    "BillingProductCreateValidation",
    "BillingProductUpdateValidation",
    "BillingRunCreateValidation",
    "BillingRunUpdateValidation",
    "BillingSubscriptionCreateValidation",
    "BillingSubscriptionUpdateValidation",
    "BillingUsageAllocationCreateValidation",
    "BillingUsageEventCreateValidation",
]


BillingAccountCreateValidation = build_create_validation(
    "BillingAccountCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingAccount.",
    required_uuid=("tenant_id",),
    required_text=("code", "display_name"),
)

BillingAccountUpdateValidation = build_update_validation(
    "BillingAccountUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingAccount.",
    optional_text=("code", "display_name", "email", "external_ref"),
    optional_any=("attributes",),
)

BillingProductCreateValidation = build_create_validation(
    "BillingProductCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingProduct.",
    required_uuid=("tenant_id",),
    required_text=("code", "name"),
)

BillingProductUpdateValidation = build_update_validation(
    "BillingProductUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingProduct.",
    optional_text=("code", "name", "description"),
    optional_any=("attributes",),
)

BillingPriceCreateValidation = build_create_validation(
    "BillingPriceCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingPrice.",
    required_uuid=("tenant_id", "product_id"),
    required_text=("code", "price_type", "currency", "meter_code"),
)

BillingPriceUpdateValidation = build_update_validation(
    "BillingPriceUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingPrice.",
    optional_text=(
        "code",
        "price_type",
        "currency",
        "interval_unit",
        "usage_unit",
        "meter_code",
    ),
    optional_any=(
        "unit_amount",
        "interval_count",
        "trial_period_days",
        "attributes",
    ),
)

BillingSubscriptionCreateValidation = build_create_validation(
    "BillingSubscriptionCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingSubscription.",
    required_uuid=("tenant_id", "account_id", "price_id"),
)

BillingSubscriptionUpdateValidation = build_update_validation(
    "BillingSubscriptionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingSubscription.",
    optional_text=("external_ref",),
    optional_datetime=(
        "current_period_start",
        "current_period_end",
        "cancel_at",
    ),
    optional_any=("attributes",),
)

BillingRunCreateValidation = build_create_validation(
    "BillingRunCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingRun.",
    required_uuid=("tenant_id",),
    required_text=("run_type", "idempotency_key"),
    required_datetime=("period_start", "period_end"),
)

BillingRunUpdateValidation = build_update_validation(
    "BillingRunUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingRun.",
    optional_uuid=("account_id", "subscription_id"),
    optional_text=("status", "external_ref", "error_message"),
    optional_datetime=("started_at", "finished_at"),
    optional_any=("attributes",),
)

BillingUsageEventCreateValidation = build_create_validation(
    "BillingUsageEventCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingUsageEvent.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("meter_code",),
    required_any=("quantity",),
)

BillingEntitlementBucketCreateValidation = build_create_validation(
    "BillingEntitlementBucketCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingEntitlementBucket.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("meter_code",),
    required_datetime=("period_start", "period_end"),
    required_any=("included_quantity",),
)

BillingEntitlementBucketUpdateValidation = build_update_validation(
    "BillingEntitlementBucketUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingEntitlementBucket.",
    optional_uuid=("subscription_id", "price_id"),
    optional_text=("meter_code", "external_ref"),
    optional_datetime=("period_start", "period_end"),
    optional_any=(
        "included_quantity",
        "rollover_quantity",
        "attributes",
    ),
)

BillingUsageAllocationCreateValidation = build_create_validation(
    "BillingUsageAllocationCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingUsageAllocation.",
    required_uuid=("tenant_id", "usage_event_id", "entitlement_bucket_id"),
    required_any=("allocated_quantity",),
)

BillingInvoiceCreateValidation = build_create_validation(
    "BillingInvoiceCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingInvoice.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("currency",),
)

BillingInvoiceUpdateValidation = build_update_validation(
    "BillingInvoiceUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingInvoice.",
    optional_uuid=("account_id", "subscription_id"),
    optional_text=("number", "currency"),
    optional_datetime=("due_at",),
    optional_any=(
        "subtotal_amount",
        "tax_amount",
        "total_amount",
        "attributes",
    ),
)

BillingCreditNoteCreateValidation = build_create_validation(
    "BillingCreditNoteCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingCreditNote.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("currency",),
)

BillingCreditNoteUpdateValidation = build_update_validation(
    "BillingCreditNoteUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingCreditNote.",
    optional_uuid=("invoice_id",),
    optional_text=("status", "number", "currency", "external_ref"),
    optional_datetime=("issued_at", "voided_at"),
    optional_any=("total_amount", "attributes"),
)

BillingAdjustmentCreateValidation = build_create_validation(
    "BillingAdjustmentCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingAdjustment.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("kind", "currency"),
    required_any=("amount",),
)

BillingAdjustmentUpdateValidation = build_update_validation(
    "BillingAdjustmentUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingAdjustment.",
    optional_uuid=("invoice_id", "credit_note_id"),
    optional_text=("reason", "external_ref"),
    optional_datetime=("occurred_at",),
    optional_any=("attributes",),
)

BillingInvoiceLineCreateValidation = build_create_validation(
    "BillingInvoiceLineCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingInvoiceLine.",
    required_uuid=("tenant_id", "invoice_id"),
    required_any=("quantity", "amount"),
)

BillingInvoiceLineUpdateValidation = build_update_validation(
    "BillingInvoiceLineUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingInvoiceLine.",
    optional_uuid=("price_id",),
    optional_text=("description",),
    optional_datetime=("period_start", "period_end"),
    optional_any=("quantity", "unit_amount", "amount", "attributes"),
)

BillingPaymentCreateValidation = build_create_validation(
    "BillingPaymentCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingPayment.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("currency",),
    required_any=("amount",),
)

BillingPaymentUpdateValidation = build_update_validation(
    "BillingPaymentUpdateValidation",
    module=__name__,
    doc="Validate update payloads for BillingPayment.",
    optional_uuid=("invoice_id",),
    optional_text=("status", "currency", "provider", "external_ref"),
    optional_datetime=("received_at", "failed_at"),
    optional_any=("amount", "attributes"),
)

BillingPaymentAllocationCreateValidation = build_create_validation(
    "BillingPaymentAllocationCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingPaymentAllocation.",
    required_uuid=("tenant_id", "payment_id", "invoice_id"),
    required_any=("amount",),
)

BillingLedgerEntryCreateValidation = build_create_validation(
    "BillingLedgerEntryCreateValidation",
    module=__name__,
    doc="Validate create payloads for BillingLedgerEntry.",
    required_uuid=("tenant_id", "account_id"),
    required_text=("direction", "currency"),
    required_any=("amount",),
)
