"""Provides a service contract for PluginCapabilityGrant services."""

__all__ = ["IPluginCapabilityGrantService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.domain import PluginCapabilityGrantDE


class IPluginCapabilityGrantService(ICrudService[PluginCapabilityGrantDE], ABC):
    """A service contract for plugin capability grants."""

    @abstractmethod
    async def entity_set_action_grant(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Grant capabilities in global scope."""

    @abstractmethod
    async def action_grant(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Grant capabilities in tenant scope."""

    @abstractmethod
    async def entity_action_revoke(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Revoke a grant in global scope."""

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
        """Revoke a grant in tenant scope."""

    @abstractmethod
    async def resolve_capability(
        self,
        *,
        tenant_id: uuid.UUID | None,
        plugin_key: str,
        capability: str,
    ) -> tuple[bool, uuid.UUID | None, PluginCapabilityGrantDE | None]:
        """Resolve capability using tenant-first/global fallback precedence."""
