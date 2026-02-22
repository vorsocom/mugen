"""Provides a service contract for TenantMembership-related services."""

__all__ = ["ITenantMembershipService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import TenantMembershipDE


class ITenantMembershipService(
    ICrudService[TenantMembershipDE],
    ABC,
):
    """A service contract for TenantMembership-related services."""

    @abstractmethod
    async def action_suspend(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Suspend a tenant membership."""

    @abstractmethod
    async def action_unsuspend(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Unsuspend a tenant membership."""

    @abstractmethod
    async def action_remove(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Remove a tenant membership."""
