"""Provides a domain entity for the Adjustment DB model."""

__all__ = ["AdjustmentDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class AdjustmentDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing Adjustment DB model."""

    account_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    credit_note_id: uuid.UUID | None = None

    kind: str | None = None  # credit / debit
    currency: str | None = None
    amount: int | None = None
    occurred_at: datetime | None = None
    reason: str | None = None
    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    account: "AccountDE | None" = None  # type: ignore
    invoice: "InvoiceDE | None" = None  # type: ignore
    credit_note: "CreditNoteDE | None" = None  # type: ignore
