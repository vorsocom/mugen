"""Provides a service contract for WorkItemDE-related services."""

__all__ = ["IWorkItemService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.channel_orchestration.domain import WorkItemDE


class IWorkItemService(ICrudService[WorkItemDE], ABC):
    """A service contract for WorkItemDE-related services."""

    @abstractmethod
    async def action_create_from_channel(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Normalize and persist canonical intake envelope data."""

    @abstractmethod
    async def action_link_to_case(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID | None,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Row-version guarded linkage of a work item to case/workflow records."""

    @abstractmethod
    async def action_replay(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID | None,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Return the canonical stored envelope for deterministic replay."""
