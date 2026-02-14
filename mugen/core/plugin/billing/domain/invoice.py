"""Provides a domain entity for the Invoice DB model."""

__all__ = ["InvoiceDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class InvoiceDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the billing Invoice DB model."""

    account_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None

    status: str | None = None  # draft / issued / paid / void / uncollectible
    number: str | None = None

    currency: str | None = None

    subtotal_amount: int | None = None
    tax_amount: int | None = None
    total_amount: int | None = None
    amount_due: int | None = None

    issued_at: datetime | None = None
    due_at: datetime | None = None
    paid_at: datetime | None = None
    voided_at: datetime | None = None

    attributes: dict[str, Any] | None = None

    lines: Sequence["InvoiceLineDE"] | None = None  # type: ignore
    credit_notes: Sequence["CreditNoteDE"] | None = None  # type: ignore
    adjustments: Sequence["AdjustmentDE"] | None = None  # type: ignore
    payments: Sequence["PaymentDE"] | None = None  # type: ignore
    allocations: Sequence["PaymentAllocationDE"] | None = None  # type: ignore
