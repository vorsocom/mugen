"""Provides a service contract for ConsentRecordDE-related services."""

__all__ = ["IConsentRecordService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_governance.domain import ConsentRecordDE


class IConsentRecordService(ICrudService[ConsentRecordDE], ABC):
    """A service contract for ConsentRecordDE-related services."""

    @abstractmethod
    async def action_record_consent(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Record a consent event."""

    @abstractmethod
    async def action_withdraw_consent(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Withdraw a previously granted consent."""
