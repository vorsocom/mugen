"""Provides a service contract for KeyRef-related services."""

__all__ = ["IKeyRefService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.service.key_provider import ResolvedKeyMaterial
from mugen.core.plugin.acp.domain import KeyRefDE


class IKeyRefService(ICrudService[KeyRefDE], ABC):
    """A service contract for key reference registry operations."""

    @abstractmethod
    async def entity_set_action_rotate(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Rotate (activate) a key reference for global scope."""

    @abstractmethod
    async def action_rotate(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Rotate (activate) a key reference for tenant scope."""

    @abstractmethod
    async def entity_action_retire(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Retire a key reference in global scope."""

    @abstractmethod
    async def action_retire(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Retire a key reference in tenant scope."""

    @abstractmethod
    async def entity_action_destroy(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Destroy a key reference in global scope."""

    @abstractmethod
    async def action_destroy(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Destroy a key reference in tenant scope."""

    @abstractmethod
    async def resolve_active_for_purpose(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
    ) -> KeyRefDE | None:
        """Resolve tenant-first (then global) active key for the purpose."""

    @abstractmethod
    async def resolve_secret_for_purpose(
        self,
        *,
        tenant_id: uuid.UUID | None,
        purpose: str,
    ) -> ResolvedKeyMaterial | None:
        """Resolve active key material for purpose with fallback semantics."""
