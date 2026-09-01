"""Provides a CRUD/action contract for profile Subscription assignments."""

__all__ = ["IServiceProfileSubscriptionService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.service_profile.domain import ServiceProfileSubscriptionDE


class IServiceProfileSubscriptionService(
    ICrudService[ServiceProfileSubscriptionDE],
    ABC,
):
    """A service contract for commercial allocation lifecycle actions."""

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
        """Activate a draft Subscription assignment."""

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
        """Disable an active Subscription assignment."""
