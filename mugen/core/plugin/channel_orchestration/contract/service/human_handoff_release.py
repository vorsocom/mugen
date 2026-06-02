"""Contracts for human handoff release hooks."""

from __future__ import annotations

__all__ = ["HumanHandoffReleased", "IHumanHandoffReleaseHandler"]

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
import uuid

from mugen.core.plugin.channel_orchestration.domain import HumanHandoffSessionDE


@dataclass(frozen=True, slots=True)
class HumanHandoffReleased:
    """Normalized release event passed to downstream handoff hooks."""

    tenant_id: uuid.UUID
    session: HumanHandoffSessionDE
    actor_user_id: uuid.UUID | None
    reason: str | None
    deactivated_at: datetime


class IHumanHandoffReleaseHandler(Protocol):  # pragma: no cover
    """Implemented by downstream apps that handle released handoffs."""

    async def on_handoff_released(
        self,
        event: HumanHandoffReleased,
    ) -> None:
        """Handle a released handoff session."""
        ...
