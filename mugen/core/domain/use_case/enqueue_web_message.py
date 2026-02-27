"""Use-case interactor for web enqueue validation and job construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mugen.core.domain.entity import ConversationEntity, QueuedMessageJobEntity


@dataclass(slots=True, frozen=True)
class BuildQueuedMessageJobUseCase:
    """Build a queue job while enforcing message contract invariants."""

    accepted_message_types: set[str]

    @classmethod
    def with_defaults(cls) -> "BuildQueuedMessageJobUseCase":
        return cls(
            accepted_message_types={"text", "audio", "video", "file", "image", "composed"}
        )

    def handle(  # pylint: disable=too-many-arguments
        self,
        *,
        job_id: str,
        auth_user: str,
        conversation_id: str,
        message_type: str,
        text: str | None,
        metadata: dict[str, Any] | None,
        file_path: str | None,
        mime_type: str | None,
        original_filename: str | None,
        client_message_id: str,
    ) -> QueuedMessageJobEntity:
        conversation = ConversationEntity.build(
            conversation_id=conversation_id,
            owner_user_id=auth_user,
        )
        if not isinstance(job_id, str) or job_id.strip() == "":
            raise ValueError("job_id must be a non-empty string")
        if not isinstance(client_message_id, str) or client_message_id.strip() == "":
            raise ValueError("client_message_id must be a non-empty string")

        normalized_type = self._normalize_message_type(message_type)

        payload_metadata: dict[str, Any] = {}
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            payload_metadata = dict(metadata)

        if normalized_type == "text":
            if text is None or str(text).strip() == "":
                raise ValueError("text is required for message_type=text")
        elif normalized_type != "composed":
            if file_path in [None, ""]:
                raise ValueError(f"file is required for message_type={normalized_type}")

        normalized_original_filename = None
        if original_filename not in [None, ""]:
            normalized_original_filename = str(original_filename)

        normalized_mime_type = None
        if mime_type not in [None, ""]:
            normalized_mime_type = str(mime_type)

        normalized_file_path = None
        if file_path not in [None, ""]:
            normalized_file_path = str(file_path)

        return QueuedMessageJobEntity(
            job_id=job_id.strip(),
            conversation_id=conversation.conversation_id,
            sender=conversation.owner_user_id,
            message_type=normalized_type,
            text=text,
            metadata=payload_metadata,
            file_path=normalized_file_path,
            mime_type=normalized_mime_type,
            original_filename=normalized_original_filename,
            client_message_id=client_message_id.strip(),
        )

    def _normalize_message_type(self, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("message_type is required")

        normalized = value.strip().lower()
        if normalized == "":
            raise ValueError("message_type is required")

        if normalized not in self.accepted_message_types:
            raise ValueError(f"Unsupported message_type: {normalized}")

        return normalized
