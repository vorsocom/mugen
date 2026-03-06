"""Stable scope primitives for tenant-aware context resolution."""

from __future__ import annotations

__all__ = ["ContextScope"]

from dataclasses import dataclass


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("ContextScope values must be strings or None.")
    normalized = value.strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class ContextScope:
    """Stable tenant and conversation scope for one context turn."""

    tenant_id: str
    platform: str | None = None
    channel_id: str | None = None
    room_id: str | None = None
    sender_id: str | None = None
    conversation_id: str | None = None
    case_id: str | None = None
    workflow_id: str | None = None

    def __post_init__(self) -> None:
        tenant_id = _normalize_optional_text(self.tenant_id)
        if tenant_id is None:
            raise ValueError("ContextScope.tenant_id is required.")
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "platform", _normalize_optional_text(self.platform))
        object.__setattr__(self, "channel_id", _normalize_optional_text(self.channel_id))
        object.__setattr__(self, "room_id", _normalize_optional_text(self.room_id))
        object.__setattr__(self, "sender_id", _normalize_optional_text(self.sender_id))
        object.__setattr__(
            self,
            "conversation_id",
            _normalize_optional_text(self.conversation_id),
        )
        object.__setattr__(self, "case_id", _normalize_optional_text(self.case_id))
        object.__setattr__(
            self,
            "workflow_id",
            _normalize_optional_text(self.workflow_id),
        )
