"""Use-case interactor for composed-message normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class NormalizeComposedMessageUseCase:
    """Normalize and validate composed message payloads."""

    max_attachments: int | None = None

    # pylint: disable=too-many-branches
    # pylint: disable=too-many-locals
    def handle(self, message: Any) -> dict[str, Any]:
        if not isinstance(message, dict):
            raise ValueError("message must be an object for composed messages")

        composition_mode = self._require_non_empty(
            message.get("composition_mode"),
            "message.composition_mode",
        ).lower()
        if composition_mode not in {
            "message_with_attachments",
            "attachment_with_caption",
        }:
            raise ValueError(
                "message.composition_mode must be one of "
                "message_with_attachments or attachment_with_caption"
            )

        raw_attachments = message.get("attachments")
        if not isinstance(raw_attachments, list):
            raise ValueError("message.attachments must be a list")

        normalized_attachments: list[dict[str, Any]] = []
        attachments_by_id: dict[str, dict[str, Any]] = {}
        for raw_attachment in raw_attachments:
            if not isinstance(raw_attachment, dict):
                raise ValueError("message.attachments items must be objects")

            attachment_id = self._require_non_empty(
                raw_attachment.get("id"),
                "message.attachments[].id",
            )
            if attachment_id in attachments_by_id:
                raise ValueError("message.attachments contains duplicate ids")

            file_path = self._require_non_empty(
                raw_attachment.get("file_path"),
                "message.attachments[].file_path",
            )
            mime_type = str(raw_attachment.get("mime_type") or "").strip().lower()
            original_filename = raw_attachment.get("original_filename")
            if original_filename is not None:
                original_filename = str(original_filename)

            attachment_metadata = raw_attachment.get("metadata")
            if attachment_metadata is None:
                attachment_metadata = {}
            elif not isinstance(attachment_metadata, dict):
                raise ValueError("message.attachments[].metadata must be an object")

            caption = raw_attachment.get("caption")
            normalized_caption = None
            if caption is not None:
                normalized_caption = str(caption).strip()

            normalized_attachment = {
                "id": attachment_id,
                "file_path": file_path,
                "mime_type": mime_type,
                "original_filename": original_filename,
                "metadata": dict(attachment_metadata),
                "caption": normalized_caption,
            }
            attachments_by_id[attachment_id] = normalized_attachment
            normalized_attachments.append(dict(normalized_attachment))

        max_attachments = self.max_attachments
        if isinstance(max_attachments, int) and max_attachments > 0:
            if len(normalized_attachments) > max_attachments:
                raise ValueError("message.attachments exceeds max attachments per message")

        raw_parts = message.get("parts")
        if not isinstance(raw_parts, list):
            raise ValueError("message.parts must be a list")

        normalized_parts: list[dict[str, Any]] = []
        has_non_empty_text = False
        for raw_part in raw_parts:
            if not isinstance(raw_part, dict):
                raise ValueError("message.parts items must be objects")

            part_type = self._require_non_empty(
                raw_part.get("type"),
                "message.parts[].type",
            ).lower()
            if part_type == "text":
                text_value = str(raw_part.get("text", ""))
                if text_value.strip() != "":
                    has_non_empty_text = True
                normalized_parts.append({"type": "text", "text": text_value})
                continue

            if part_type != "attachment":
                raise ValueError(f"Unsupported composed part type: {part_type}")

            attachment_id = self._require_non_empty(
                raw_part.get("id"),
                "message.parts[].id",
            )
            attachment = attachments_by_id.get(attachment_id)
            if attachment is None:
                raise ValueError(
                    "message.parts includes attachment id not found in message.attachments"
                )

            caption = raw_part.get("caption")
            normalized_caption = attachment.get("caption")
            if caption is not None:
                normalized_caption = str(caption).strip()

            part_metadata = raw_part.get("metadata")
            normalized_part_metadata = dict(attachment.get("metadata") or {})
            if part_metadata is not None:
                if not isinstance(part_metadata, dict):
                    raise ValueError("message.parts[].metadata must be an object")
                normalized_part_metadata = dict(part_metadata)

            normalized_parts.append(
                {
                    "type": "attachment",
                    "id": attachment_id,
                    "caption": normalized_caption,
                    "metadata": normalized_part_metadata,
                    "mime_type": attachment.get("mime_type"),
                    "original_filename": attachment.get("original_filename"),
                }
            )

        if composition_mode == "attachment_with_caption":
            if any(part.get("type") == "text" for part in normalized_parts):
                raise ValueError(
                    "message.parts text entries are not allowed for attachment_with_caption"
                )
            if not normalized_attachments:
                raise ValueError(
                    "message.attachments requires at least one attachment for "
                    "attachment_with_caption"
                )
            if any(
                str(attachment.get("caption") or "").strip() == ""
                for attachment in normalized_attachments
            ):
                raise ValueError(
                    "message.attachments caption is required for attachment_with_caption"
                )
        elif not has_non_empty_text and not normalized_attachments:
            raise ValueError("message.parts must include text content or attachments")

        normalized: dict[str, Any] = {
            "composition_mode": composition_mode,
            "parts": normalized_parts,
            "attachments": normalized_attachments,
        }
        request_metadata = message.get("metadata")
        if request_metadata is not None and not isinstance(request_metadata, dict):
            raise ValueError("message.metadata must be an object")
        if isinstance(request_metadata, dict):
            normalized["metadata"] = dict(request_metadata)

        if message.get("client_message_id") is not None:
            normalized["client_message_id"] = str(message.get("client_message_id"))

        return normalized

    @staticmethod
    def _require_non_empty(value: Any, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a non-empty string")

        normalized = value.strip()
        if normalized == "":
            raise ValueError(f"{field_name} must be a non-empty string")

        return normalized
