"""Provides a service contract for BlocklistEntryDE-related services."""

__all__ = ["IBlocklistEntryService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.channel_orchestration.domain import BlocklistEntryDE


class IBlocklistEntryService(ICrudService[BlocklistEntryDE], ABC):
    """A service contract for BlocklistEntryDE-related services."""

    @abstractmethod
    async def action_block_sender(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Block a sender for tenant/channel orchestration intake."""

    @abstractmethod
    async def action_unblock_sender(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Unblock a sender for tenant/channel orchestration intake."""
