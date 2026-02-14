"""Provides a service contract for UsageRecordDE-related services."""

__all__ = ["IUsageRecordService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_metering.domain import UsageRecordDE


class IUsageRecordService(
    ICrudService[UsageRecordDE],
    ABC,
):
    """A service contract for UsageRecordDE-related services."""

    @abstractmethod
    async def action_rate_record(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Rate a usage record and hand off billable usage to billing."""

    @abstractmethod
    async def action_void_record(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Void a usage record and related outputs if present."""
