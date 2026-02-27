"""Domain entity for queued web message jobs."""

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class QueuedMessageJobEntity:
    """Validated queued message payload."""

    job_id: str
    conversation_id: str
    sender: str
    message_type: str
    text: str | None
    metadata: dict[str, Any]
    file_path: str | None
    mime_type: str | None
    original_filename: str | None
    client_message_id: str

    def as_pending_record(self, *, now_iso: str) -> dict[str, Any]:
        """Build a pending queue-record payload used by storage adapters."""
        return {
            "id": self.job_id,
            "conversation_id": self.conversation_id,
            "sender": self.sender,
            "message_type": self.message_type,
            "text": self.text,
            "metadata": dict(self.metadata),
            "file_path": self.file_path,
            "mime_type": self.mime_type,
            "original_filename": self.original_filename,
            "client_message_id": self.client_message_id,
            "status": "pending",
            "attempts": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
            "lease_expires_at": None,
            "error": None,
        }
