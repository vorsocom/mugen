"""Ports for durable web-runtime persistence operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class WebRuntimeTailEvent:
    """One durable event row returned by stream-tail queries."""

    id: int
    event: str
    data: dict[str, Any]
    created_at: str | None
    stream_generation: str
    stream_version: int


@dataclass(frozen=True)
class WebRuntimeTailBatch:
    """Ordered durable stream-tail batch."""

    stream_generation: str
    max_event_id: int
    requested_after_event_id: int = 0
    effective_after_event_id: int = 0
    first_event_id: int | None = None
    events: list[WebRuntimeTailEvent] = field(default_factory=list)


class IWebRuntimeStore(ABC):
    """Storage port for web runtime queue, event stream, and media token state."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close backend resources asynchronously."""

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate backend connectivity and required tables."""

    @abstractmethod
    async def ensure_conversation_owner(
        self,
        *,
        conversation_id: str,
        auth_user: str,
        create_if_missing: bool,
        stream_generation: str,
        stream_version: int,
    ) -> None:
        """Validate or create conversation ownership state."""

    @abstractmethod
    async def count_pending_jobs(self) -> int:
        """Return current pending queue depth."""

    @abstractmethod
    async def insert_pending_job(
        self,
        *,
        job_id: str,
        conversation_id: str,
        sender: str,
        message_type: str,
        payload: dict[str, Any],
        client_message_id: str,
    ) -> None:
        """Persist a pending queue job."""

    @abstractmethod
    async def claim_next_job(
        self,
        *,
        now_iso: str,
        now_epoch: float,
        queue_processing_lease_seconds: float,
    ) -> tuple[dict[str, Any] | None, int]:
        """Claim one pending job and return (job, recovered_stale_count)."""

    @abstractmethod
    async def processing_owner_matches(
        self,
        *,
        job_id: str,
        expected_attempt: int,
    ) -> bool:
        """Return True if job is still processing by the expected attempt owner."""

    @abstractmethod
    async def renew_processing_lease(
        self,
        *,
        job_id: str,
        expected_attempt: int | None,
        lease_expires_at: datetime,
        updated_at: datetime,
    ) -> bool:
        """Renew processing lease for a claimed job."""

    @abstractmethod
    async def append_event(
        self,
        *,
        conversation_id: str,
        event_type: str,
        payload: dict[str, Any],
        created_at: datetime,
        event_log_version: int,
        replay_max_events: int,
        new_stream_generation: str,
    ) -> dict[str, Any]:
        """Append an event and update stream cursor metadata."""

    @abstractmethod
    async def list_media_tokens(self) -> list[dict[str, Any]]:
        """List all media-token rows."""

    @abstractmethod
    async def tail_events_since(
        self,
        *,
        conversation_id: str,
        stream_generation: str | None,
        after_event_id: int,
        limit: int,
    ) -> WebRuntimeTailBatch:
        """Tail durable events strictly after event-id cursor."""

    @abstractmethod
    async def delete_media_token(self, *, token: str) -> None:
        """Delete one media token."""

    @abstractmethod
    async def list_active_queue_payloads(self) -> list[Any]:
        """List payloads for pending/processing queue jobs."""

    @abstractmethod
    async def insert_media_token(
        self,
        *,
        token: str,
        owner_user_id: str,
        conversation_id: str,
        file_path: str,
        mime_type: str | None,
        filename: str | None,
        expires_at: datetime,
    ) -> None:
        """Insert a media download token."""

    @abstractmethod
    async def get_media_token(self, *, token: str) -> dict[str, Any] | None:
        """Fetch one media token row."""

    @abstractmethod
    async def recover_stale_processing_jobs(self, *, now_ts: datetime) -> int:
        """Recover stale processing jobs back to pending."""

    @abstractmethod
    async def mark_job_status(
        self,
        *,
        job_id: str,
        status: str,
        error: str | None,
        expected_attempt: int | None,
        now_iso: str,
        event_log_version: int,
    ) -> int:
        """Apply queue terminal/non-terminal status transition.

        Returns rowcount for the final status update.
        """

    @abstractmethod
    async def read_queue_state(self, *, queue_state_version: int) -> dict[str, Any]:
        """Read full queue state snapshot."""

    @abstractmethod
    async def write_queue_state(self, *, queue_state: dict[str, Any]) -> None:
        """Replace queue state snapshot."""

    @abstractmethod
    async def read_event_log(
        self,
        *,
        conversation_id: str,
        event_log_version: int,
        replay_max_events: int,
        new_stream_generation: str,
    ) -> dict[str, Any]:
        """Read event-log snapshot for one conversation."""

    @abstractmethod
    async def write_event_log(
        self,
        *,
        conversation_id: str,
        payload: dict[str, Any],
        event_log_version: int,
        now_epoch: float,
        new_stream_generation: str,
    ) -> None:
        """Replace event-log snapshot for one conversation."""
