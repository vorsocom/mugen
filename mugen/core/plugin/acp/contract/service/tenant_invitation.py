"""Provides a service contract for TenantInvitation-related services."""

__all__ = ["ITenantInvitationService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import TenantInvitationDE


class ITenantInvitationService(
    ICrudService[TenantInvitationDE],
    ABC,
):
    """A service contract for TenantDomain-related services."""

    @abstractmethod
    async def action_resend(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> dict[str, Any]:
        """Resend an invitation for a tenant member."""

    @abstractmethod
    async def action_revoke(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Revoke an invitation for a tenant member."""

    @abstractmethod
    async def redeem_authenticated(
        self,
        *,
        tenant_id: uuid.UUID,
        invitation_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        token: str,
    ) -> tuple[dict[str, Any], int]:
        """Redeem an invitation for an authenticated ACP user."""
