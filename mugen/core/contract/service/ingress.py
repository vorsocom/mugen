"""Contracts for shared durable messaging ingress."""

from __future__ import annotations

__all__ = [
    "IMessagingIngressService",
    "MessagingIngressCheckpointUpdate",
    "MessagingIngressEvent",
    "MessagingIngressStageEntry",
    "MessagingIngressStageResult",
]

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _normalize_required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    normalized = value.strip()
    if normalized == "":
        raise ValueError(f"{field_name} is required.")
    return normalized


def _normalize_optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string when provided.")
    normalized = value.strip()
    return normalized if normalized != "" else None


def _normalize_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dict.")
    return dict(value)


def _normalize_datetime(value: object, *, field_name: str) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime when provided.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class MessagingIngressEvent:
    """Canonical inbound event envelope for external messaging platforms."""

    version: int
    platform: str
    runtime_profile_key: str
    source_mode: str
    event_type: str
    event_id: str | None
    dedupe_key: str
    identifier_type: str
    identifier_value: str | None = None
    room_id: str | None = None
    sender: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    provider_context: dict[str, Any] = field(default_factory=dict)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", int(self.version))
        if self.version <= 0:
            raise ValueError("MessagingIngressEvent.version must be positive.")
        object.__setattr__(
            self,
            "platform",
            _normalize_required_text(self.platform, field_name="MessagingIngressEvent.platform"),
        )
        object.__setattr__(
            self,
            "runtime_profile_key",
            _normalize_required_text(
                self.runtime_profile_key,
                field_name="MessagingIngressEvent.runtime_profile_key",
            ),
        )
        object.__setattr__(
            self,
            "source_mode",
            _normalize_required_text(
                self.source_mode,
                field_name="MessagingIngressEvent.source_mode",
            ),
        )
        object.__setattr__(
            self,
            "event_type",
            _normalize_required_text(
                self.event_type,
                field_name="MessagingIngressEvent.event_type",
            ),
        )
        object.__setattr__(
            self,
            "event_id",
            _normalize_optional_text(
                self.event_id,
                field_name="MessagingIngressEvent.event_id",
            ),
        )
        object.__setattr__(
            self,
            "dedupe_key",
            _normalize_required_text(
                self.dedupe_key,
                field_name="MessagingIngressEvent.dedupe_key",
            ),
        )
        object.__setattr__(
            self,
            "identifier_type",
            _normalize_required_text(
                self.identifier_type,
                field_name="MessagingIngressEvent.identifier_type",
            ),
        )
        object.__setattr__(
            self,
            "identifier_value",
            _normalize_optional_text(
                self.identifier_value,
                field_name="MessagingIngressEvent.identifier_value",
            ),
        )
        object.__setattr__(
            self,
            "room_id",
            _normalize_optional_text(
                self.room_id,
                field_name="MessagingIngressEvent.room_id",
            ),
        )
        object.__setattr__(
            self,
            "sender",
            _normalize_optional_text(
                self.sender,
                field_name="MessagingIngressEvent.sender",
            ),
        )
        object.__setattr__(
            self,
            "payload",
            _normalize_mapping(self.payload, field_name="MessagingIngressEvent.payload"),
        )
        object.__setattr__(
            self,
            "provider_context",
            _normalize_mapping(
                self.provider_context,
                field_name="MessagingIngressEvent.provider_context",
            ),
        )
        object.__setattr__(
            self,
            "received_at",
            _normalize_datetime(
                self.received_at,
                field_name="MessagingIngressEvent.received_at",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe plain dictionary."""
        payload = asdict(self)
        payload["received_at"] = self.received_at.astimezone(timezone.utc).isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class MessagingIngressStageEntry:
    """One canonical event plus the IPC command that should consume it."""

    ipc_command: str
    event: MessagingIngressEvent
    dedupe_ttl_seconds: int = 86400

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ipc_command",
            _normalize_required_text(
                self.ipc_command,
                field_name="MessagingIngressStageEntry.ipc_command",
            ),
        )
        if not isinstance(self.event, MessagingIngressEvent):
            raise TypeError("MessagingIngressStageEntry.event must be MessagingIngressEvent.")
        object.__setattr__(self, "dedupe_ttl_seconds", int(self.dedupe_ttl_seconds))
        if self.dedupe_ttl_seconds <= 0:
            raise ValueError(
                "MessagingIngressStageEntry.dedupe_ttl_seconds must be positive."
            )


@dataclass(frozen=True, slots=True)
class MessagingIngressCheckpointUpdate:
    """Checkpoint mutation staged transactionally with ingress events."""

    platform: str
    runtime_profile_key: str
    checkpoint_key: str
    checkpoint_value: str
    provider_context: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "platform",
            _normalize_required_text(
                self.platform,
                field_name="MessagingIngressCheckpointUpdate.platform",
            ),
        )
        object.__setattr__(
            self,
            "runtime_profile_key",
            _normalize_required_text(
                self.runtime_profile_key,
                field_name="MessagingIngressCheckpointUpdate.runtime_profile_key",
            ),
        )
        object.__setattr__(
            self,
            "checkpoint_key",
            _normalize_required_text(
                self.checkpoint_key,
                field_name="MessagingIngressCheckpointUpdate.checkpoint_key",
            ),
        )
        object.__setattr__(
            self,
            "checkpoint_value",
            _normalize_required_text(
                self.checkpoint_value,
                field_name="MessagingIngressCheckpointUpdate.checkpoint_value",
            ),
        )
        object.__setattr__(
            self,
            "provider_context",
            _normalize_mapping(
                self.provider_context,
                field_name="MessagingIngressCheckpointUpdate.provider_context",
            ),
        )
        object.__setattr__(
            self,
            "observed_at",
            _normalize_datetime(
                self.observed_at,
                field_name="MessagingIngressCheckpointUpdate.observed_at",
            ),
        )


@dataclass(frozen=True, slots=True)
class MessagingIngressStageResult:
    """Summary of one staging transaction."""

    staged_count: int
    duplicate_count: int
    checkpoint_count: int


class IMessagingIngressService(ABC):
    """Contract for shared durable ingress staging and worker dispatch."""

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate provider readiness and required schema presence."""

    @abstractmethod
    async def ensure_started(self) -> None:
        """Start the background ingress worker if it is not already running."""

    @abstractmethod
    async def stage(
        self,
        entries: list[MessagingIngressStageEntry],
        *,
        checkpoints: list[MessagingIngressCheckpointUpdate] | None = None,
    ) -> MessagingIngressStageResult:
        """Durably stage canonical events and optional checkpoints."""

    @abstractmethod
    async def get_checkpoint(
        self,
        *,
        platform: str,
        runtime_profile_key: str,
        checkpoint_key: str,
    ) -> str | None:
        """Fetch the latest checkpoint value for one platform/profile key."""

    @abstractmethod
    async def aclose(self) -> None:
        """Stop the background worker and release any runtime resources."""
