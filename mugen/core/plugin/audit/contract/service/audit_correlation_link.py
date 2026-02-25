"""Provides a service contract for AuditCorrelationLinkDE-related services."""

__all__ = ["IAuditCorrelationLinkService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.audit.domain import AuditCorrelationLinkDE


class IAuditCorrelationLinkService(ICrudService[AuditCorrelationLinkDE], ABC):
    """A service contract for audit correlation-link services."""

    @abstractmethod
    async def entity_set_action_resolve_trace(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Resolve links and graph projection for a trace query."""

    @abstractmethod
    async def action_resolve_trace(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Resolve links and graph for tenant-scoped trace queries."""
