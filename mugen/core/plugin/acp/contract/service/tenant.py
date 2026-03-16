"""Provides a service contract for Tenant-related services."""

__all__ = ["ITenantService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import TenantDE


class ITenantService(
    ICrudService[TenantDE],
    ABC,
):
    """A service contract for Tenant-related services."""

    @abstractmethod
    async def entity_action_deactivate(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Deactivate a Tenant."""

    @abstractmethod
    async def entity_action_reactivate(
        self,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a Tenant."""
