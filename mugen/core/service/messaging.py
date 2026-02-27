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
from mugen.core.domain.use_case import NormalizeComposedMessageUseCase


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _thread_version: int = 1

    _thread_list_version: int = 1

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
        self._cp_extensions: list[ICPExtension] = []
        self._ct_extensions: list[ICTExtension] = []
        self._ctx_extensions: list[ICTXExtension] = []
        self._mh_extensions: list[IMHExtension] = []
        self._rag_extensions: list[IRAGExtension] = []
        self._rpp_extensions: list[IRPPExtension] = []

        self._cp_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._ct_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._ctx_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._mh_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._rag_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._rpp_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._normalize_composed_message_use_case = NormalizeComposedMessageUseCase()

    @staticmethod
    def _extension_platform_key(ext: Any) -> tuple[str, ...]:
        platforms = getattr(ext, "platforms", [])
        if not isinstance(platforms, list):
            return tuple()
        return tuple(sorted(str(item) for item in platforms))

    def _extension_logical_key(
        self,
        ext: Any,
        *,
        kind: str,
    ) -> tuple[str, str, tuple[str, ...]]:
        return (
            kind,
            f"{type(ext).__module__}.{type(ext).__qualname__}",
            self._extension_platform_key(ext),
        )

    @staticmethod
    def _register_extension(
        *,
        ext: Any,
        ext_list: list,
        ext_keys: set[tuple[str, str, tuple[str, ...]]],
        logical_key: tuple[str, str, tuple[str, ...]],
    ) -> None:
        if ext in ext_list:
            raise ValueError("Extension already registered (instance duplicate).")
        if logical_key in ext_keys:
            raise ValueError("Extension already registered (logical duplicate).")
        ext_list.append(ext)
        ext_keys.add(logical_key)

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

    def _normalize_composed_message(self, message: Any) -> dict[str, Any]:
        return self._normalize_composed_message_use_case.handle(message)

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
        self._register_extension(
            ext=ext,
            ext_list=self._cp_extensions,
            ext_keys=self._cp_extension_keys,
            logical_key=self._extension_logical_key(ext, kind="cp"),
        )

    def register_ct_extension(self, ext: ICTExtension) -> None:
        self._register_extension(
            ext=ext,
            ext_list=self._ct_extensions,
            ext_keys=self._ct_extension_keys,
            logical_key=self._extension_logical_key(ext, kind="ct"),
        )

    def register_ctx_extension(self, ext: ICTXExtension) -> None:
        self._register_extension(
            ext=ext,
            ext_list=self._ctx_extensions,
            ext_keys=self._ctx_extension_keys,
            logical_key=self._extension_logical_key(ext, kind="ctx"),
        )

    def register_mh_extension(self, ext: IMHExtension) -> None:
        self._register_extension(
            ext=ext,
            ext_list=self._mh_extensions,
            ext_keys=self._mh_extension_keys,
            logical_key=self._extension_logical_key(ext, kind="mh"),
        )

    def register_rag_extension(self, ext: IRAGExtension) -> None:
        self._register_extension(
            ext=ext,
            ext_list=self._rag_extensions,
            ext_keys=self._rag_extension_keys,
            logical_key=self._extension_logical_key(ext, kind="rag"),
        )

    def register_rpp_extension(self, ext: IRPPExtension) -> None:
        self._register_extension(
            ext=ext,
            ext_list=self._rpp_extensions,
            ext_keys=self._rpp_extension_keys,
            logical_key=self._extension_logical_key(ext, kind="rpp"),
        )
