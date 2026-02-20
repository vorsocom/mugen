"""Provides an implementation of IMessagingService."""

__all__ = ["DefaultMessagingService"]

from types import SimpleNamespace
from typing import Any

from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.ctx import ICTXExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rag import IRAGExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _thread_version: int = 1

    _thread_list_version: int = 1

    _cp_extensions: list[ICPExtension] = []

    _ct_extensions: list[ICTExtension] = []

    _ctx_extensions: list[ICTXExtension] = []

    _mh_extensions: list[IMHExtension] = []

    _rag_extensions: list[IRAGExtension] = []

    _rpp_extensions: list[IRPPExtension] = []

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace,
        completion_gateway: ICompletionGateway,
        keyval_storage_gateway: IKeyValStorageGateway,
        logging_gateway: ILoggingGateway,
        user_service: IUserService,
    ) -> None:
        self._config = config
        self._completion_gateway = completion_gateway
        self._keyval_storage_gateway = keyval_storage_gateway
        self._logging_gateway = logging_gateway
        self._user_service = user_service

    async def handle_audio_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"audio"},
        )

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: audio.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded an audio file.",
            message_context=handler_responses,
        )

    async def handle_composed_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        normalized_message = self._normalize_composed_message(message)
        parts = list(normalized_message["parts"])
        attachments = list(normalized_message["attachments"])
        composition_mode = str(normalized_message["composition_mode"])
        client_message_id = normalized_message.get("client_message_id")

        prompt = self._build_composed_text_prompt(parts=parts)
        attachment_context = self._build_composed_attachment_context(
            attachments=attachments,
            composition_mode=composition_mode,
        )
        media_context = await self._collect_composed_media_context(
            platform=platform,
            room_id=room_id,
            sender=sender,
            attachments=attachments,
            composition_mode=composition_mode,
            client_message_id=client_message_id,
        )

        combined_context: list[dict] = []
        if attachment_context is not None:
            combined_context += attachment_context
        combined_context += media_context

        request_metadata = normalized_message.get("metadata")
        if isinstance(request_metadata, dict):
            combined_context.append(
                {
                    "type": "composed_metadata",
                    "content": {"metadata": dict(request_metadata)},
                }
            )

        message_context = combined_context if combined_context else None
        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=prompt,
            message_context=message_context,
        )

    async def handle_file_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"file"},
        )

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: file.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded a file.",
            message_context=handler_responses,
        )

    async def handle_image_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"image"},
        )

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: image.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded an image file.",
            message_context=handler_responses,
        )

    async def handle_text_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: str,
        message_context: list[dict] | None = None,
    ) -> list[dict] | None:
        # Call message handlers.
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            # Filter extensions that don't support the
            # calling platform.
            if not mh_ext.platform_supported(platform):
                continue

            # Filter extensions that don't handle text
            # messages.
            if "text" not in mh_ext.message_types:
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
                message_context=message_context,
            )

            if resp:
                handler_responses += resp

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: text.",
                }
            ]

        return handler_responses

    async def handle_video_message(
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
    ) -> list[dict] | None:
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"video"},
        )

        if not handler_responses:
            return [
                {
                    "type": "text",
                    "content": "Unsupported message type: video.",
                }
            ]

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded video file.",
            message_context=handler_responses,
        )

    async def _collect_message_handler_responses(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_types: set[str],
    ) -> list[dict]:
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            if not mh_ext.platform_supported(platform):
                continue

            supported_message_types = getattr(mh_ext, "message_types", [])
            if not isinstance(supported_message_types, list):
                continue

            if not any(message_type in supported_message_types for message_type in message_types):
                continue

            resp = await mh_ext.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
            )

            if resp:
                handler_responses += resp

        return handler_responses

    async def _collect_composed_media_context(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        attachments: list[dict[str, Any]],
        composition_mode: str,
        client_message_id: Any,
    ) -> list[dict]:
        media_context: list[dict] = []
        for attachment in attachments:
            message_payload = {
                "file_path": attachment.get("file_path"),
                "mime_type": attachment.get("mime_type"),
                "filename": attachment.get("original_filename"),
                "metadata": dict(attachment.get("metadata") or {}),
                "client_message_id": client_message_id,
                "attachment_id": attachment.get("id"),
                "caption": attachment.get("caption"),
                "composition_mode": composition_mode,
            }
            inferred_type = self._infer_media_message_type(message_payload.get("mime_type"))
            handler_responses = await self._collect_message_handler_responses(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message_payload,
                message_types={inferred_type},
            )
            if handler_responses:
                media_context += handler_responses

        return media_context

    @staticmethod
    def _build_composed_text_prompt(*, parts: list[dict[str, Any]]) -> str:
        segments: list[str] = []
        for part in parts:
            part_type = str(part.get("type", "")).strip().lower()
            if part_type == "text":
                segments.append(str(part.get("text", "")))
                continue

            if part_type != "attachment":
                continue

            attachment_id = str(part.get("id", "")).strip()
            if attachment_id == "":
                attachment_id = "unknown"
            placeholder = f"[attachment:{attachment_id}]"

            caption = str(part.get("caption") or "").strip()
            if caption != "":
                placeholder = f"{placeholder} caption={caption}"

            segments.append(placeholder)

        if not segments:
            return ""

        return "\n".join(segments)

    @staticmethod
    def _build_composed_attachment_context(
        *,
        attachments: list[dict[str, Any]],
        composition_mode: str,
    ) -> list[dict] | None:
        if not attachments:
            return None

        context: list[dict] = []
        for index, attachment in enumerate(attachments, start=1):
            context.append(
                {
                    "type": "attachment",
                    "content": {
                        "index": index,
                        "id": attachment.get("id"),
                        "mime_type": attachment.get("mime_type"),
                        "filename": attachment.get("original_filename"),
                        "caption": attachment.get("caption"),
                        "metadata": dict(attachment.get("metadata") or {}),
                        "composition_mode": composition_mode,
                    },
                }
            )

        return context

    @staticmethod
    def _infer_media_message_type(mime_type: Any) -> str:
        normalized_mime = str(mime_type or "").strip().lower()
        if normalized_mime.startswith("audio/"):
            return "audio"
        if normalized_mime.startswith("video/"):
            return "video"
        if normalized_mime.startswith("image/"):
            return "image"
        return "file"

    @staticmethod
    def _require_non_empty(value: Any, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a non-empty string")

        normalized = value.strip()
        if normalized == "":
            raise ValueError(f"{field_name} must be a non-empty string")

        return normalized

    # pylint: disable=too-many-branches
    # pylint: disable=too-many-locals
    def _normalize_composed_message(self, message: Any) -> dict[str, Any]:
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

    @property
    def cp_extensions(self) -> list[ICPExtension]:
        return self._cp_extensions

    @property
    def ct_extensions(self) -> list[ICTExtension]:
        return self._ct_extensions

    @property
    def ctx_extensions(self) -> list[ICTXExtension]:
        return self._ctx_extensions

    @property
    def mh_extensions(self) -> list[IMHExtension]:
        return self._mh_extensions

    @property
    def rag_extensions(self) -> list[IRAGExtension]:
        return self._rag_extensions

    @property
    def rpp_extensions(self) -> list[IRPPExtension]:
        return self._rpp_extensions

    def register_cp_extension(self, ext: ICPExtension) -> None:
        self._cp_extensions.append(ext)

    def register_ct_extension(self, ext: ICTExtension) -> None:
        self._ct_extensions.append(ext)

    def register_ctx_extension(self, ext: ICTXExtension) -> None:
        self._ctx_extensions.append(ext)

    def register_mh_extension(self, ext: IMHExtension) -> None:
        self._mh_extensions.append(ext)

    def register_rag_extension(self, ext: IRAGExtension) -> None:
        self._rag_extensions.append(ext)

    def register_rpp_extension(self, ext: IRPPExtension) -> None:
        self._rpp_extensions.append(ext)
