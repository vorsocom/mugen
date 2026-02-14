"""Provides a service contract for PaymentAllocationDE-related services."""

__all__ = ["IPaymentAllocationService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.billing.domain import PaymentAllocationDE


class IPaymentAllocationService(
    ICrudService[PaymentAllocationDE],
    ABC,
):
    """A service contract for PaymentAllocationDE-related services."""

    @abstractmethod
    async def action_sync_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Recompute linked invoice amounts/status from payment allocations."""
