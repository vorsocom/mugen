"""Provides a service contract for PriceDE-related services."""

__all__ = ["IPriceService"]

from abc import ABC, abstractmethod
from typing import Any
import uuid

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.billing.domain import PriceDE


class IPriceService(
    ICrudService[PriceDE],
    ABC,
):
    """A service contract for PriceDE-related services."""

    @abstractmethod
    async def entity_action_archive(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Archive a global Price."""
