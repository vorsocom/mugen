"""Provides a service contract for SubscriptionDE-related services."""

__all__ = ["ISubscriptionService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.billing.domain import SubscriptionDE


class ISubscriptionService(
    ICrudService[SubscriptionDE],
    ABC,
):
    """A service contract for SubscriptionDE-related services."""

    @abstractmethod
    async def action_cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Cancel a subscription."""

    @abstractmethod
    async def action_reactivate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a subscription."""
