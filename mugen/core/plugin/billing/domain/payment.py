"""Provides a domain entity for the Payment DB model."""

__all__ = ["PaymentDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class PaymentDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing Payment DB model."""

    account_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None

    status: str | None = None  # pending / succeeded / failed / canceled / refunded

    currency: str | None = None
    amount: int | None = None  # minor units

    provider: str | None = None
    external_ref: str | None = None

    received_at: datetime | None = None
    failed_at: datetime | None = None

    attributes: dict[str, Any] | None = None

    allocations: Sequence["PaymentAllocationDE"] | None = None  # type: ignore
