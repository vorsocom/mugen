"""Provides a domain entity for the InvoiceLine DB model."""

__all__ = ["InvoiceLineDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class InvoiceLineDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing InvoiceLine DB model."""

    invoice_id: uuid.UUID | None = None
    price_id: uuid.UUID | None = None

    description: str | None = None
    quantity: int | None = None

    unit_amount: int | None = None  # minor units
    amount: int | None = None  # minor units

    period_start: datetime | None = None
    period_end: datetime | None = None

    attributes: dict[str, Any] | None = None
