"""Provides a CRUD/action contract for Service Profiles."""

__all__ = ["IServiceProfileService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.service_profile.domain import ServiceProfileDE


class IServiceProfileService(ICrudService[ServiceProfileDE], ABC):
    """A service contract for Service Profile CRUD and lifecycle actions."""

    @abstractmethod
    async def action_activate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Activate a draft Service Profile."""

    @abstractmethod
    async def action_disable(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Disable an active Service Profile."""
