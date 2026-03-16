"""Provides a domain entity for the LedgerEntry DB model."""

__all__ = ["LedgerEntryDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class LedgerEntryDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing LedgerEntry DB model."""

    account_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None = None

    direction: str | None = None  # debit / credit

    currency: str | None = None
    amount: int | None = None  # minor units (unsigned; direction carries sign)

    occurred_at: datetime | None = None
    description: str | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None
