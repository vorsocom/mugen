"""Provides a service contract for LegalHold services."""

__all__ = ["ILegalHoldService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_governance.domain import LegalHoldDE


class ILegalHoldService(ICrudService[LegalHoldDE], ABC):
    """A service contract for legal hold synchronization actions."""

    @abstractmethod
    async def action_place_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Place legal hold and synchronize target resource state."""

    @abstractmethod
    async def action_release_hold(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Release legal hold and synchronize target resource state."""
