"""Provides a service contract for AuditBizTraceEventDE-related services."""

__all__ = ["IAuditBizTraceEventService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.audit.domain import AuditBizTraceEventDE


class IAuditBizTraceEventService(ICrudService[AuditBizTraceEventDE], ABC):
    """A service contract for audit business-trace-event services."""

    @abstractmethod
    async def entity_set_action_inspect_trace(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Inspect business-trace timeline for a trace query."""

    @abstractmethod
    async def action_inspect_trace(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Inspect tenant-scoped business-trace timeline."""
