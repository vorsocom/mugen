"""Provides an implementation of IMessagingService."""

from __future__ import annotations

__all__ = ["DefaultMessagingService"]

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

from mugen.core.constants import GLOBAL_TENANT_ID
from mugen.core.contract.agent import IAgentRuntime
from mugen.core.contract.context import ContextScope, IContextEngine
from mugen.core.contract.extension.cp import ICPExtension
from mugen.core.contract.extension.ct import ICTExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.extension.rpp import IRPPExtension
from mugen.core.contract.gateway.completion import ICompletionGateway
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.messaging import IMessagingService, MessagingTurnRequest
from mugen.core.contract.service.user import IUserService
from mugen.core.domain.use_case import NormalizeComposedMessageUseCase
from mugen.core.service.context_scope_resolution import context_scope_from_ingress_route
from mugen.core.utility.config_value import parse_optional_positive_finite_float


# pylint: disable=too-many-instance-attributes
class DefaultMessagingService(IMessagingService):
    """The default implementation of IMessagingService."""

    _default_extension_timeout_seconds: float = 10.0

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        config: SimpleNamespace,
        completion_gateway: ICompletionGateway,
        context_engine_service: IContextEngine,
        logging_gateway: ILoggingGateway,
        user_service: IUserService,
        agent_runtime_service: IAgentRuntime | None = None,
    ) -> None:
        self._config = config
        self._completion_gateway = completion_gateway
        self._context_engine_service = context_engine_service
        self._agent_runtime_service = agent_runtime_service
        self._logging_gateway = logging_gateway
        self._user_service = user_service
        self._cp_extensions: list[ICPExtension] = []
        self._ct_extensions: list[ICTExtension] = []
        self._mh_extensions: list[IMHExtension] = []
        self._rpp_extensions: list[IRPPExtension] = []

        self._cp_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._ct_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._mh_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._rpp_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        self._critical_extension_keys: set[tuple[str, str, tuple[str, ...]]] = set()

        self._normalize_composed_message_use_case = NormalizeComposedMessageUseCase()
        self._mh_mode = self._resolve_mh_mode()
        self._builtin_text_handler = self._build_builtin_text_handler()
        self._extension_timeout_seconds = self._resolve_extension_timeout_seconds()
        self._extension_metrics: dict[str, int] = {}

    def _increment_extension_metric(self, metric_name: str, amount: int = 1) -> None:
        self._extension_metrics[metric_name] = (
            self._extension_metrics.get(metric_name, 0) + amount
        )

    def _resolve_extension_timeout_seconds(self) -> float | None:
        environment = str(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "environment", "")
        ).strip().lower()
        production_mode = environment == "production"
        messaging_cfg = getattr(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "messaging", None),
            "extension_timeout_seconds",
            None,
        )
        if messaging_cfg in [None, ""]:
            if production_mode:
                self._logging_gateway.warning(
                    "Messaging extension timeout missing in production; "
                    f"using default {self._default_extension_timeout_seconds:.1f}s."
                )
                return self._default_extension_timeout_seconds
            return None
        return parse_optional_positive_finite_float(
            messaging_cfg,
            "mugen.messaging.extension_timeout_seconds",
        )

    def _resolve_mh_mode(self) -> str:
        messaging_cfg = getattr(
            getattr(self._config, "mugen", SimpleNamespace()),
            "messaging",
            SimpleNamespace(),
        )
        if isinstance(messaging_cfg, dict):
            configured_mode = messaging_cfg.get("mh_mode")
        else:
            configured_mode = getattr(messaging_cfg, "mh_mode", None)
        mode = str(configured_mode or "").strip().lower()
        if mode not in {"optional", "required"}:
            raise ValueError(
                "Invalid configuration: mugen.messaging.mh_mode is required and must be "
                "'optional' or 'required'."
            )
        return mode

    def _build_builtin_text_handler(self):
        try:
            module = importlib.import_module("mugen.core.extension.mh.default_text")
            handler_class = getattr(module, "DefaultTextMHExtension")
            return handler_class(
                completion_gateway=self._completion_gateway,
                config=self._config,
                context_engine_service=self._context_engine_service,
                agent_runtime_service=self._agent_runtime_service,
                logging_gateway=self._logging_gateway,
                messaging_service=self,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "Failed to initialize built-in text messaging pipeline."
            ) from exc

    def _is_critical_extension(self, extension: Any, *, kind: str) -> bool:
        key = self._extension_logical_key(extension, kind=kind)
        return key in self._critical_extension_keys

    def _handle_extension_handler_failure(
        self,
        *,
        extension_name: str,
        extension: Any,
        kind: str,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        if self._is_critical_extension(extension, kind=kind):
            self._increment_extension_metric("messaging.extensions.fail_closed")
            self._logging_gateway.error(
                "Critical messaging extension failed "
                f"(extension={extension_name} kind={kind})."
            )
            if cause is None:
                raise RuntimeError(message)
            raise RuntimeError(message) from cause
        self._increment_extension_metric("messaging.extensions.fail_open")
        self._logging_gateway.warning(message)

    async def _invoke_message_handler(
        self,
        *,
        extension: IMHExtension,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_context: list[dict] | None = None,
        attachment_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope,
    ) -> list[dict] | None:
        coroutine = extension.handle_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_context=message_context,
            attachment_context=attachment_context,
            ingress_metadata=ingress_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=scope,
        )
        extension_name = f"{type(extension).__module__}.{type(extension).__qualname__}"

        timeout_seconds = self._extension_timeout_seconds
        if timeout_seconds is None:
            try:
                return await coroutine
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._increment_extension_metric("messaging.extensions.exception")
                self._handle_extension_handler_failure(
                    extension_name=extension_name,
                    extension=extension,
                    kind="mh",
                    message=(
                        "Messaging extension handler failed "
                        f"(extension={extension_name} "
                        f"error_type={type(exc).__name__} error={exc})."
                    ),
                    cause=exc,
                )
                return None

        try:
            return await asyncio.wait_for(coroutine, timeout=timeout_seconds)
        except asyncio.TimeoutError as exc:
            self._increment_extension_metric("messaging.extensions.timeout")
            self._handle_extension_handler_failure(
                extension_name=extension_name,
                extension=extension,
                kind="mh",
                message=(
                    "Messaging extension handler timed out "
                    f"(extension={extension_name} "
                    f"timeout_seconds={timeout_seconds})."
                ),
                cause=exc,
            )
            return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._increment_extension_metric("messaging.extensions.exception")
            self._handle_extension_handler_failure(
                extension_name=extension_name,
                extension=extension,
                kind="mh",
                message=(
                    "Messaging extension handler failed "
                    f"(extension={extension_name} "
                    f"error_type={type(exc).__name__} error={exc})."
                ),
                cause=exc,
            )
            return None

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

    async def handle_audio_message(  # pylint: disable=too-many-arguments
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
        message_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope | None = None,
    ) -> list[dict] | None:
        resolved_scope, resolved_context, _, resolved_metadata = self._resolve_turn_scope(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_context=message_context,
            attachment_context=None,
            ingress_metadata=ingress_metadata,
            scope=scope,
        )
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"audio"},
            message_context=resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )
        if not handler_responses:
            return [{"type": "text", "content": "Unsupported message type: audio."}]
        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded an audio file.",
            message_context=handler_responses + resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )

    async def handle_composed_message(  # pylint: disable=too-many-arguments
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
        message_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope | None = None,
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
        resolved_scope, resolved_context, resolved_attachments, resolved_metadata = (
            self._resolve_turn_scope(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=normalized_message,
                message_context=message_context,
                attachment_context=attachment_context,
                ingress_metadata=ingress_metadata,
                scope=scope,
            )
        )
        media_context = await self._collect_composed_media_context(
            platform=platform,
            room_id=room_id,
            sender=sender,
            attachments=attachments,
            composition_mode=composition_mode,
            client_message_id=client_message_id,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )
        combined_context = [*resolved_context, *media_context]
        request_metadata = normalized_message.get("metadata")
        if isinstance(request_metadata, dict):
            combined_context.append(
                {
                    "type": "composed_metadata",
                    "content": {"metadata": dict(request_metadata)},
                }
            )

        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=prompt,
            message_context=combined_context,
            attachment_context=resolved_attachments,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )

    async def handle_file_message(  # pylint: disable=too-many-arguments
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
        message_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope | None = None,
    ) -> list[dict] | None:
        resolved_scope, resolved_context, _, resolved_metadata = self._resolve_turn_scope(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_context=message_context,
            attachment_context=None,
            ingress_metadata=ingress_metadata,
            scope=scope,
        )
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"file"},
            message_context=resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )
        if not handler_responses:
            return [{"type": "text", "content": "Unsupported message type: file."}]
        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded a file.",
            message_context=handler_responses + resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )

    async def handle_image_message(  # pylint: disable=too-many-arguments
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
        message_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope | None = None,
    ) -> list[dict] | None:
        resolved_scope, resolved_context, _, resolved_metadata = self._resolve_turn_scope(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_context=message_context,
            attachment_context=None,
            ingress_metadata=ingress_metadata,
            scope=scope,
        )
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"image"},
            message_context=resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )
        if not handler_responses:
            return [{"type": "text", "content": "Unsupported message type: image."}]
        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded an image file.",
            message_context=handler_responses + resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )

    async def handle_text_message(  # pylint: disable=too-many-arguments
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: str,
        message_context: list[dict] | None = None,
        attachment_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope | None = None,
    ) -> list[dict] | None:
        resolved_scope, resolved_context, resolved_attachments, resolved_metadata = (
            self._resolve_turn_scope(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
                message_context=message_context,
                attachment_context=attachment_context,
                ingress_metadata=ingress_metadata,
                scope=scope,
            )
        )
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"text"},
            message_context=resolved_context,
            attachment_context=resolved_attachments,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )
        if not handler_responses:
            if self._mh_mode == "required":
                raise RuntimeError(
                    "Messaging runtime requires at least one MH extension for text handling "
                    "when mugen.messaging.mh_mode='required'."
                )
            return await self._builtin_text_handler.handle_message(
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
                message_context=resolved_context,
                attachment_context=resolved_attachments,
                ingress_metadata=resolved_metadata,
                message_id=message_id,
                trace_id=trace_id,
                scope=resolved_scope,
            )
        return handler_responses

    async def handle_video_message(  # pylint: disable=too-many-arguments
        self,
        platform: str,
        room_id: str,
        sender: str,
        message: dict,
        message_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope | None = None,
    ) -> list[dict] | None:
        resolved_scope, resolved_context, _, resolved_metadata = self._resolve_turn_scope(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_context=message_context,
            attachment_context=None,
            ingress_metadata=ingress_metadata,
            scope=scope,
        )
        handler_responses = await self._collect_message_handler_responses(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message=message,
            message_types={"video"},
            message_context=resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )
        if not handler_responses:
            return [{"type": "text", "content": "Unsupported message type: video."}]
        return await self.handle_text_message(
            platform=platform,
            room_id=room_id,
            sender=sender,
            message="Uploaded video file.",
            message_context=handler_responses + resolved_context,
            ingress_metadata=resolved_metadata,
            message_id=message_id,
            trace_id=trace_id,
            scope=resolved_scope,
        )

    async def handle_message(
        self,
        request: MessagingTurnRequest,
    ) -> list[dict[str, Any]] | None:
        if request.message_type == "text":
            if not isinstance(request.message, str):
                raise ValueError("Text messaging turns require str payloads.")
            return await self.handle_text_message(
                platform=request.scope.platform or "",
                room_id=request.scope.room_id or request.scope.conversation_id or "",
                sender=request.scope.sender_id or "",
                message=request.message,
                message_context=request.message_context,
                attachment_context=request.attachment_context,
                ingress_metadata=request.ingress_metadata,
                message_id=request.message_id,
                trace_id=request.trace_id,
                scope=request.scope,
            )
        if request.message_type == "composed":
            if not isinstance(request.message, dict):
                raise ValueError("Composed messaging turns require object payloads.")
            return await self.handle_composed_message(
                platform=request.scope.platform or "",
                room_id=request.scope.room_id or request.scope.conversation_id or "",
                sender=request.scope.sender_id or "",
                message=request.message,
                message_context=request.message_context,
                ingress_metadata=request.ingress_metadata,
                message_id=request.message_id,
                trace_id=request.trace_id,
                scope=request.scope,
            )
        if request.message_type == "audio":
            if not isinstance(request.message, dict):
                raise ValueError("Audio messaging turns require object payloads.")
            return await self.handle_audio_message(
                platform=request.scope.platform or "",
                room_id=request.scope.room_id or request.scope.conversation_id or "",
                sender=request.scope.sender_id or "",
                message=request.message,
                message_context=request.message_context,
                ingress_metadata=request.ingress_metadata,
                message_id=request.message_id,
                trace_id=request.trace_id,
                scope=request.scope,
            )
        if request.message_type == "file":
            if not isinstance(request.message, dict):
                raise ValueError("File messaging turns require object payloads.")
            return await self.handle_file_message(
                platform=request.scope.platform or "",
                room_id=request.scope.room_id or request.scope.conversation_id or "",
                sender=request.scope.sender_id or "",
                message=request.message,
                message_context=request.message_context,
                ingress_metadata=request.ingress_metadata,
                message_id=request.message_id,
                trace_id=request.trace_id,
                scope=request.scope,
            )
        if request.message_type == "image":
            if not isinstance(request.message, dict):
                raise ValueError("Image messaging turns require object payloads.")
            return await self.handle_image_message(
                platform=request.scope.platform or "",
                room_id=request.scope.room_id or request.scope.conversation_id or "",
                sender=request.scope.sender_id or "",
                message=request.message,
                message_context=request.message_context,
                ingress_metadata=request.ingress_metadata,
                message_id=request.message_id,
                trace_id=request.trace_id,
                scope=request.scope,
            )
        if request.message_type == "video":
            if not isinstance(request.message, dict):
                raise ValueError("Video messaging turns require object payloads.")
            return await self.handle_video_message(
                platform=request.scope.platform or "",
                room_id=request.scope.room_id or request.scope.conversation_id or "",
                sender=request.scope.sender_id or "",
                message=request.message,
                message_context=request.message_context,
                ingress_metadata=request.ingress_metadata,
                message_id=request.message_id,
                trace_id=request.trace_id,
                scope=request.scope,
            )
        raise ValueError(f"Unsupported message type: {request.message_type}")

    async def _collect_message_handler_responses(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_types: set[str],
        message_context: list[dict] | None = None,
        attachment_context: list[dict] | None = None,
        ingress_metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
        scope: ContextScope,
    ) -> list[dict]:
        handler_responses: list[dict] = []
        for mh_ext in self._mh_extensions:
            if not mh_ext.platform_supported(platform):
                continue
            extension_name = f"{type(mh_ext).__module__}.{type(mh_ext).__qualname__}"
            supported_message_types = getattr(mh_ext, "message_types", [])
            if not isinstance(supported_message_types, list):
                continue
            if not any(message_type in supported_message_types for message_type in message_types):
                continue
            resp = await self._invoke_message_handler(
                extension=mh_ext,
                platform=platform,
                room_id=room_id,
                sender=sender,
                message=message,
                message_context=message_context,
                attachment_context=attachment_context,
                ingress_metadata=ingress_metadata,
                message_id=message_id,
                trace_id=trace_id,
                scope=scope,
            )
            if resp is None:
                continue
            if not isinstance(resp, list):
                self._logging_gateway.warning(
                    "Messaging extension handler returned invalid response type "
                    f"(extension={extension_name} "
                    f"response_type={type(resp).__name__})."
                )
                continue
            for item in resp:
                if isinstance(item, dict):
                    handler_responses.append(item)
                    continue
                self._logging_gateway.warning(
                    "Messaging extension handler returned invalid response item "
                    f"(extension={extension_name} "
                    f"item_type={type(item).__name__})."
                )
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
        ingress_metadata: dict[str, Any],
        message_id: str | None,
        trace_id: str | None,
        scope: ContextScope,
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
                ingress_metadata=ingress_metadata,
                message_id=message_id,
                trace_id=trace_id,
                scope=scope,
            )
            if handler_responses:
                media_context += handler_responses
        return media_context

    def _resolve_turn_scope(
        self,
        *,
        platform: str,
        room_id: str,
        sender: str,
        message: dict | str,
        message_context: list[dict] | None,
        attachment_context: list[dict] | None,
        ingress_metadata: dict[str, Any] | None,
        scope: ContextScope | None,
    ) -> tuple[ContextScope, list[dict], list[dict], dict[str, Any]]:
        normalized_message_context = self._normalize_context_items(message_context)
        normalized_attachment_context = self._normalize_context_items(attachment_context)
        merged_metadata = self._merge_ingress_metadata(
            message=message,
            ingress_metadata=ingress_metadata,
        )
        ingress_route = self._extract_ingress_route(
            message=message,
            message_context=normalized_message_context,
            ingress_metadata=merged_metadata,
        )
        if scope is None:
            resolved = context_scope_from_ingress_route(
                platform=platform,
                channel_key=platform,
                room_id=room_id,
                sender_id=sender,
                ingress_route=ingress_route,
                ingress_metadata=merged_metadata,
                conversation_id=self._metadata_text(merged_metadata.get("conversation_id"))
                or room_id,
                case_id=self._metadata_text(merged_metadata.get("case_id")),
                workflow_id=self._metadata_text(merged_metadata.get("workflow_id")),
                source=f"{platform}.messaging",
            )
            resolved_scope = resolved.scope
            resolved_route = resolved.ingress_route
            tenant_resolution = resolved.tenant_resolution
        else:
            resolved_scope = scope
            resolved_route = self._route_from_scope(
                scope=scope,
                platform=platform,
                ingress_route=ingress_route,
            )
            tenant_resolution = resolved_route.get("tenant_resolution")
            if not isinstance(tenant_resolution, dict):
                tenant_resolution = {
                    "mode": (
                        "resolved"
                        if scope.tenant_id != str(GLOBAL_TENANT_ID)
                        else "fallback_global"
                    ),
                    "reason_code": None
                    if scope.tenant_id != str(GLOBAL_TENANT_ID)
                    else "explicit_scope",
                    "source": f"{platform}.messaging",
                }
                resolved_route["tenant_resolution"] = tenant_resolution
        merged_metadata["ingress_route"] = dict(resolved_route)
        merged_metadata["tenant_resolution"] = dict(tenant_resolution)
        normalized_message_context = self._ensure_ingress_route_message_context(
            normalized_message_context,
            resolved_route,
        )
        return (
            resolved_scope,
            normalized_message_context,
            normalized_attachment_context,
            merged_metadata,
        )

    @staticmethod
    def _normalize_context_items(value: list[dict] | None) -> list[dict]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    @staticmethod
    def _message_payload_metadata(message: dict | str) -> dict[str, Any]:
        if not isinstance(message, dict):
            return {}
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            return {}
        return dict(metadata)

    def _merge_ingress_metadata(
        self,
        *,
        message: dict | str,
        ingress_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        merged = self._message_payload_metadata(message)
        if isinstance(ingress_metadata, dict):
            merged.update(dict(ingress_metadata))
        return merged

    @staticmethod
    def _metadata_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _extract_ingress_route(
        self,
        *,
        message: dict | str,
        message_context: list[dict],
        ingress_metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        route = ingress_metadata.get("ingress_route")
        if isinstance(route, dict):
            return dict(route)
        message_metadata = self._message_payload_metadata(message)
        route = message_metadata.get("ingress_route")
        if isinstance(route, dict):
            return dict(route)
        for item in message_context:
            if item.get("type") != "ingress_route":
                continue
            content = item.get("content")
            if isinstance(content, dict):
                return dict(content)
        return None

    @staticmethod
    def _ensure_ingress_route_message_context(
        message_context: list[dict],
        ingress_route: dict[str, Any],
    ) -> list[dict]:
        for item in message_context:
            if item.get("type") == "ingress_route" and isinstance(item.get("content"), dict):
                return message_context
        return [
            *message_context,
            {"type": "ingress_route", "content": dict(ingress_route)},
        ]

    @staticmethod
    def _route_from_scope(
        *,
        scope: ContextScope,
        platform: str,
        ingress_route: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(ingress_route, dict):
            route_tenant_id = str(ingress_route.get("tenant_id") or "")
            if route_tenant_id not in {"", scope.tenant_id}:
                raise RuntimeError("Ingress route tenant_id does not match ContextScope.")
            normalized = dict(ingress_route)
            normalized["tenant_id"] = scope.tenant_id
            normalized.setdefault("platform", scope.platform or platform)
            normalized.setdefault("channel_key", scope.channel_id or platform)
            normalized.setdefault("identifier_claims", {})
            return normalized
        return {
            "tenant_id": scope.tenant_id,
            "tenant_slug": "global"
            if scope.tenant_id == str(GLOBAL_TENANT_ID)
            else None,
            "platform": scope.platform or platform,
            "channel_key": scope.channel_id or platform,
            "identifier_claims": {},
            "channel_profile_id": None,
            "client_profile_id": None,
            "service_route_key": None,
            "route_key": None,
            "binding_id": None,
            "client_profile_key": None,
        }

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
            attachment_id = str(part.get("id", "")).strip() or "unknown"
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
    def mh_extensions(self) -> list[IMHExtension]:
        return self._mh_extensions

    @property
    def rpp_extensions(self) -> list[IRPPExtension]:
        return self._rpp_extensions

    def _bind_extension_with_criticality(
        self,
        *,
        ext: Any,
        ext_list: list,
        ext_keys: set[tuple[str, str, tuple[str, ...]]],
        kind: str,
        critical: bool,
    ) -> None:
        logical_key = self._extension_logical_key(ext, kind=kind)
        self._register_extension(
            ext=ext,
            ext_list=ext_list,
            ext_keys=ext_keys,
            logical_key=logical_key,
        )
        if critical:
            self._critical_extension_keys.add(logical_key)

    def bind_cp_extension(self, ext: ICPExtension, *, critical: bool = False) -> None:
        self._bind_extension_with_criticality(
            ext=ext,
            ext_list=self._cp_extensions,
            ext_keys=self._cp_extension_keys,
            kind="cp",
            critical=critical,
        )

    def bind_ct_extension(self, ext: ICTExtension, *, critical: bool = False) -> None:
        self._bind_extension_with_criticality(
            ext=ext,
            ext_list=self._ct_extensions,
            ext_keys=self._ct_extension_keys,
            kind="ct",
            critical=critical,
        )

    def bind_mh_extension(self, ext: IMHExtension, *, critical: bool = False) -> None:
        self._bind_extension_with_criticality(
            ext=ext,
            ext_list=self._mh_extensions,
            ext_keys=self._mh_extension_keys,
            kind="mh",
            critical=critical,
        )

    def bind_rpp_extension(self, ext: IRPPExtension, *, critical: bool = False) -> None:
        self._bind_extension_with_criticality(
            ext=ext,
            ext_list=self._rpp_extensions,
            ext_keys=self._rpp_extension_keys,
            kind="rpp",
            critical=critical,
        )
