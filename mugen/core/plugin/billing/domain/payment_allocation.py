"""Provides a domain entity for the PaymentAllocation DB model."""

__all__ = ["PaymentAllocationDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class PaymentAllocationDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing PaymentAllocation DB model."""

    payment_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None

    amount: int | None = None
    allocated_at: datetime | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    payment: "PaymentDE | None" = None  # type: ignore
    invoice: "InvoiceDE | None" = None  # type: ignore
