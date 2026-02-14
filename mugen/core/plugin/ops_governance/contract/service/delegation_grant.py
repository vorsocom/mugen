"""Provides a service contract for DelegationGrantDE-related services."""

__all__ = ["IDelegationGrantService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_governance.domain import DelegationGrantDE


class IDelegationGrantService(ICrudService[DelegationGrantDE], ABC):
    """A service contract for DelegationGrantDE-related services."""

    @abstractmethod
    async def action_grant_delegation(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Create a delegation grant event."""

    @abstractmethod
    async def action_revoke_delegation(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Revoke an existing delegation grant by appending a revocation event."""
