"""Provides a service contract for PolicyDefinitionDE-related services."""

__all__ = ["IPolicyDefinitionService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_governance.domain import PolicyDefinitionDE


class IPolicyDefinitionService(ICrudService[PolicyDefinitionDE], ABC):
    """A service contract for PolicyDefinitionDE-related services."""

    @abstractmethod
    async def action_evaluate_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate a policy and append a decision log event."""
