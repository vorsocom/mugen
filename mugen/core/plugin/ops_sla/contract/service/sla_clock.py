"""Provides a service contract for SlaClockDE-related services."""

__all__ = ["ISlaClockService"]

import uuid
from abc import ABC, abstractmethod
from typing import Any, Mapping

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.ops_sla.domain import SlaClockDE


class ISlaClockService(
    ICrudService[SlaClockDE],
    ABC,
):
    """A service contract for SlaClockDE-related services."""

    @abstractmethod
    async def action_start_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Start the clock for the target entity."""

    @abstractmethod
    async def action_pause_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Pause a running clock."""

    @abstractmethod
    async def action_resume_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Resume a paused clock."""

    @abstractmethod
    async def action_stop_clock(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Stop the clock and finalize elapsed time."""

    @abstractmethod
    async def action_mark_breached(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Mark the tracked clock as breached and append an event."""

    @abstractmethod
    async def action_tick(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
        entity_id: uuid.UUID | None = None,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate running clocks and emit warning/breach events once per rule."""
