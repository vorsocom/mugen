"""Provides a domain entity for the Account DB model."""

__all__ = ["AccountDE"]

from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class AccountDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the billing Account DB model."""

    code: str | None = None
    display_name: str | None = None
    email: str | None = None
    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    subscriptions: Sequence["SubscriptionDE"] | None = None  # type: ignore
    billing_runs: Sequence["BillingRunDE"] | None = None  # type: ignore
    invoices: Sequence["InvoiceDE"] | None = None  # type: ignore
    credit_notes: Sequence["CreditNoteDE"] | None = None  # type: ignore
    adjustments: Sequence["AdjustmentDE"] | None = None  # type: ignore
    payments: Sequence["PaymentDE"] | None = None  # type: ignore
    usage_events: Sequence["UsageEventDE"] | None = None  # type: ignore
    ledger_entries: Sequence["LedgerEntryDE"] | None = None  # type: ignore
    entitlement_buckets: Sequence["EntitlementBucketDE"] | None = None  # type: ignore
