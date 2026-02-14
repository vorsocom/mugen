"""Provides a domain entity for the CreditNote DB model."""

__all__ = ["CreditNoteDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class CreditNoteDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing CreditNote DB model."""

    account_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None

    status: str | None = None  # draft / issued / void
    number: str | None = None
    currency: str | None = None
    total_amount: int | None = None
    issued_at: datetime | None = None
    voided_at: datetime | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    account: "AccountDE | None" = None  # type: ignore
    invoice: "InvoiceDE | None" = None  # type: ignore
    adjustments: Sequence["AdjustmentDE"] | None = None  # type: ignore
