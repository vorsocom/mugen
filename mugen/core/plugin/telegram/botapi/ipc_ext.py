"""Provides an implementation of IIPCExtension for Telegram Bot API support."""

__all__ = ["TelegramBotAPIIPCExtension"]

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.client.telegram import ITelegramClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.contract.service.ingress_routing import (
    IIngressRoutingService,
    IngressRouteRequest,
)
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core import di
from mugen.core.service.context_scope_resolution import (
    ContextScopeResolutionError,
    resolve_ingress_route_context,
)
from mugen.core.utility.platform_runtime_profile import (
    runtime_profile_key_from_ingress_route,
    runtime_profile_scope,
)
from mugen.core.service.ingress_routing import (
    DefaultIngressRoutingService,
)
from mugen.core.utility.config_value import parse_bool_flag
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    normalize_processing_state,
)


def _telegram_client_provider():
    return di.container.telegram_client


def _config_provider():
    return di.container.config


def _logging_gateway_provider():
    return di.container.logging_gateway


def _relational_storage_gateway_provider():
    return di.container.relational_storage_gateway


def _messaging_service_provider():
    return di.container.messaging_service


def _user_service_provider():
    return di.container.user_service


class TelegramBotAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for Telegram Bot API support."""

    _event_dedup_table = "telegram_botapi_event_dedup"
    _event_dead_letter_table = "telegram_botapi_event_dead_letter"
    _default_event_dedup_ttl_seconds = 86400

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        relational_storage_gateway: IRelationalStorageGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
        telegram_client: ITelegramClient | None = None,
        ingress_routing_service: IIngressRoutingService | None = None,
    ) -> None:
        self._client = (
            telegram_client
            if telegram_client is not None
            else _telegram_client_provider()
        )
        self._config = config if config is not None else _config_provider()
        self._logging_gateway = (
            logging_gateway
            if logging_gateway is not None
            else _logging_gateway_provider()
        )
        self._relational_storage_gateway = (
            relational_storage_gateway
            if relational_storage_gateway is not None
            else _relational_storage_gateway_provider()
        )
        self._messaging_service = (
            messaging_service
            if messaging_service is not None
            else _messaging_service_provider()
        )
        self._user_service = (
            user_service if user_service is not None else _user_service_provider()
        )
        self._ingress_routing_service = ingress_routing_service
        self._event_dedup_ttl_seconds = self._resolve_event_dedup_ttl_seconds()
        self._typing_enabled = self._resolve_typing_enabled()
        self._metrics: dict[str, int] = {}

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "telegram_ingress_event",
            "telegram_botapi_update",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["telegram"]

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "telegram", SimpleNamespace()), "webhook", None),
            "dedupe_ttl_seconds",
            self._default_event_dedup_ttl_seconds,
        )
        try:
            ttl_seconds = int(raw_value)
        except (TypeError, ValueError):
            ttl_seconds = self._default_event_dedup_ttl_seconds
        if ttl_seconds <= 0:
            return self._default_event_dedup_ttl_seconds
        return ttl_seconds

    def _resolve_typing_enabled(self) -> bool:
        raw_enabled = getattr(
            getattr(getattr(self._config, "telegram", SimpleNamespace()), "typing", None),
            "enabled",
            True,
        )
        return parse_bool_flag(raw_enabled, True)

    def _ingress_router(self) -> IIngressRoutingService:
        if self._ingress_routing_service is not None:
            return self._ingress_routing_service
        self._ingress_routing_service = DefaultIngressRoutingService(
            relational_storage_gateway=self._relational_storage_gateway,
            logging_gateway=self._logging_gateway,
        )
        return self._ingress_routing_service

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def _increment_metric(self, metric_name: str) -> None:
        self._metrics[metric_name] = self._metrics.get(metric_name, 0) + 1

    @staticmethod
    def _build_event_dedupe_key(event_type: str, event_payload: dict) -> str:
        payload = json.dumps(event_payload, sort_keys=True, separators=(",", ":"))
        payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"{event_type}:{payload_hash}"

    async def _record_dead_letter(
        self,
        *,
        event_type: str,
        event_payload: dict,
        reason_code: str,
        error_message: str | None = None,
    ) -> None:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        now = self._now_utc()
        try:
            await self._relational_storage_gateway.insert_one(
                self._event_dead_letter_table,
                {
                    "event_type": event_type,
                    "dedupe_key": dedupe_key,
                    "payload": event_payload,
                    "reason_code": reason_code,
                    "error_message": error_message,
                    "status": "queued",
                    "attempts": 1,
                    "first_failed_at": now,
                    "last_failed_at": now,
                },
            )
            self._increment_metric("telegram.ipc.dead_letter.write_success")
        except SQLAlchemyError as exc:
            self._increment_metric("telegram.ipc.dead_letter.write_failure")
            self._logging_gateway.error(
                "Failed to write Telegram dead-letter event."
                f" reason_code={reason_code}"
                f" error={type(exc).__name__}: {exc}"
            )

    async def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        event_id = event_payload.get("id")
        if event_id is None:
            event_id = event_payload.get("update_id")
        if event_id is not None:
            event_id = str(event_id)
        now = self._now_utc()
        try:
            await self._relational_storage_gateway.insert_one(
                self._event_dedup_table,
                {
                    "event_type": event_type,
                    "dedupe_key": dedupe_key,
                    "event_id": event_id,
                    "last_seen_at": now,
                    "expires_at": now
                    + timedelta(seconds=self._event_dedup_ttl_seconds),
                },
            )
            self._increment_metric("telegram.ipc.dedupe.miss")
            return False
        except IntegrityError:
            self._increment_metric("telegram.ipc.dedupe.hit")
            try:
                await self._relational_storage_gateway.update_one(
                    self._event_dedup_table,
                    {
                        "event_type": event_type,
                        "dedupe_key": dedupe_key,
                    },
                    {
                        "last_seen_at": now,
                    },
                )
            except SQLAlchemyError:
                ...
            return True
        except SQLAlchemyError as exc:
            self._increment_metric("telegram.ipc.dedupe.error")
            self._logging_gateway.error(
                "Telegram dedupe lookup failed."
                f" error={type(exc).__name__}: {exc}"
            )
            return False

    @staticmethod
    def _coerce_chat_id(value: object) -> str | None:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
        return None

    @staticmethod
    def _coerce_user_id(value: object) -> str | None:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
        return None

    @staticmethod
    def _coerce_nonempty_string(value: object) -> str | None:
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
        return None

    @staticmethod
    def _compose_message_context(
        *,
        ingress_route: dict,
        extra_context: list[dict] | None = None,
    ) -> list[dict]:
        combined: list[dict] = []
        if isinstance(extra_context, list):
            combined.extend([item for item in extra_context if isinstance(item, dict)])
        combined.append(
            {
                "type": "ingress_route",
                "content": dict(ingress_route),
            }
        )
        return combined

    @staticmethod
    def _normalize_ingress_route(
        ingress_route: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(ingress_route, dict):
            return dict(ingress_route)
        return {
            "platform": "telegram",
            "channel_key": "telegram",
            "identifier_claims": {},
        }

    @staticmethod
    def _merge_ingress_metadata(
        *,
        payload: dict[str, Any],
        ingress_route: dict,
    ) -> dict[str, Any]:
        merged = dict(payload)
        metadata = merged.get("metadata")
        if isinstance(metadata, dict):
            normalized_metadata = dict(metadata)
        else:
            normalized_metadata = {}
        normalized_metadata["ingress_route"] = dict(ingress_route)
        merged["metadata"] = normalized_metadata
        return merged

    async def _resolve_ingress_route(
        self,
        *,
        path_token: str | None,
        webhook_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        claims = {"path_token": path_token} if path_token is not None else {}
        resolution = await self._ingress_router().resolve(
            IngressRouteRequest(
                platform="telegram",
                channel_key="telegram",
                identifier_type="path_token",
                identifier_value=path_token,
                claims=claims,
            )
        )
        try:
            ingress_route = resolve_ingress_route_context(
                platform="telegram",
                channel_key="telegram",
                routing=resolution,
                source="telegram.ingress_routing",
                identifier_claims=claims,
                global_fallback_reasons=(),
            )
        except ContextScopeResolutionError as exc:
            self._increment_metric("telegram.ipc.route.unresolved")
            reason_code = str(exc.reason_code or "route_unresolved")
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=webhook_payload,
                reason_code="route_unresolved",
                error_message=str(exc),
            )
            self._logging_gateway.warning(
                "Dropped Telegram webhook due to unresolved ingress route "
                f"reason_code={reason_code} path_token={path_token!r}."
            )
            return None
        return ingress_route

    async def _emit_processing_signal(
        self,
        *,
        chat_id: str,
        message_id: str | None,
        state: str,
    ) -> None:
        _ = message_id
        if self._typing_enabled is not True:
            return

        emitter = getattr(self._client, "emit_processing_signal", None)
        if not callable(emitter):
            return

        try:
            normalized_state = normalize_processing_state(state)
            result = await emitter(
                chat_id,
                state=normalized_state,
            )
            if result is False:
                self._logging_gateway.warning(
                    "Telegram thinking signal reported failure "
                    f"(chat_id={chat_id} state={normalized_state})."
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Telegram thinking signal raised unexpectedly "
                f"(chat_id={chat_id} state={state}): {exc}"
            )

    async def _register_sender_if_unknown(
        self,
        *,
        sender: str,
        room_id: str,
        user_obj: dict | None,
    ) -> None:
        known_users = await self._user_service.get_known_users_list()
        known_users = known_users if isinstance(known_users, dict) else {}
        if sender in known_users.keys():
            return

        display_name = sender
        if isinstance(user_obj, dict):
            first_name = user_obj.get("first_name")
            username = user_obj.get("username")
            if isinstance(first_name, str) and first_name.strip() != "":
                display_name = first_name.strip()
            elif isinstance(username, str) and username.strip() != "":
                display_name = username.strip()

        self._logging_gateway.debug(f"New Telegram contact: {sender}")
        await self._user_service.add_known_user(sender, display_name, room_id)

    async def _download_message_media(self, *, file_id: str) -> dict | None:
        downloaded = await self._client.download_media(file_id)
        if not isinstance(downloaded, dict):
            return None
        media_path = downloaded.get("path")
        media_mime_type = downloaded.get("mime_type")
        if not isinstance(media_path, str) or media_path == "":
            return None
        return {
            "file": media_path,
            "mime_type": media_mime_type,
            "metadata": downloaded,
        }

    async def _send_response_to_user(self, response: dict, default_chat_id: str) -> None:
        response_type = response.get("type")

        if response_type == "telegram":
            op = str(response.get("op") or "").strip().lower()
            if op == "send_message":
                text = response.get("text")
                if not isinstance(text, str):
                    self._logging_gateway.error("Missing Telegram send_message text payload.")
                    return
                chat_id = self._coerce_chat_id(response.get("chat_id")) or default_chat_id
                reply_markup = response.get("reply_markup")
                if not isinstance(reply_markup, dict):
                    reply_markup = None
                reply_to_message_id = response.get("reply_to_message_id")
                if not isinstance(reply_to_message_id, int):
                    reply_to_message_id = None
                await self._client.send_text_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                )
                return

            if op == "answer_callback":
                callback_query_id = response.get("callback_query_id")
                if not isinstance(callback_query_id, str) or callback_query_id.strip() == "":
                    self._logging_gateway.error(
                        "Missing callback_query_id for Telegram answer_callback op."
                    )
                    return
                text = response.get("text")
                if not isinstance(text, str):
                    text = None
                show_alert = response.get("show_alert")
                if not isinstance(show_alert, bool):
                    show_alert = None
                await self._client.answer_callback_query(
                    callback_query_id=callback_query_id,
                    text=text,
                    show_alert=show_alert,
                )
                return

            self._logging_gateway.error(f"Unsupported Telegram response op: {op}.")
            return

        chat_id = self._coerce_chat_id(response.get("chat_id")) or default_chat_id
        reply_to_message_id = response.get("reply_to_message_id")
        if not isinstance(reply_to_message_id, int):
            reply_to_message_id = None

        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str):
                self._logging_gateway.error("Missing text content in response payload.")
                return
            await self._client.send_text_message(
                chat_id=chat_id,
                text=content,
                reply_to_message_id=reply_to_message_id,
            )
            return

        if response_type == "audio":
            audio = response.get("file")
            if not isinstance(audio, dict):
                self._logging_gateway.error("Missing audio payload in response.")
                return
            await self._client.send_audio_message(
                chat_id=chat_id,
                audio=audio,
                reply_to_message_id=reply_to_message_id,
            )
            return

        if response_type == "file":
            document = response.get("file")
            if not isinstance(document, dict):
                self._logging_gateway.error("Missing file payload in response.")
                return
            await self._client.send_file_message(
                chat_id=chat_id,
                document=document,
                reply_to_message_id=reply_to_message_id,
            )
            return

        if response_type == "image":
            photo = response.get("file")
            if not isinstance(photo, dict):
                self._logging_gateway.error("Missing image payload in response.")
                return
            await self._client.send_image_message(
                chat_id=chat_id,
                photo=photo,
                reply_to_message_id=reply_to_message_id,
            )
            return

        if response_type == "video":
            video = response.get("file")
            if not isinstance(video, dict):
                self._logging_gateway.error("Missing video payload in response.")
                return
            await self._client.send_video_message(
                chat_id=chat_id,
                video=video,
                reply_to_message_id=reply_to_message_id,
            )
            return

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")

    async def _handle_message_update(
        self,
        update: dict,
        message: dict,
        ingress_route: dict[str, Any] | None = None,
        *,
        skip_dedupe: bool = False,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        if skip_dedupe is not True and await self._is_duplicate_event("message", message):
            self._logging_gateway.debug("Skip duplicate Telegram message event.")
            return

        chat = message.get("chat")
        chat_type = chat.get("type") if isinstance(chat, dict) else None
        if chat_type != "private":
            self._logging_gateway.info(
                "Ignoring non-private Telegram event "
                f"chat_type={chat_type!r} update_id={update.get('update_id')!r}."
            )
            return

        room_id = self._coerce_chat_id(chat.get("id") if isinstance(chat, dict) else None)
        sender = self._coerce_user_id(
            message.get("from", {}).get("id") if isinstance(message.get("from"), dict) else None
        )
        if not isinstance(room_id, str) or not isinstance(sender, str):
            self._logging_gateway.error("Malformed Telegram message payload.")
            return

        message_id = message.get("message_id")
        if message_id is not None:
            message_id = str(message_id)

        await self._register_sender_if_unknown(
            sender=sender,
            room_id=room_id,
            user_obj=message.get("from") if isinstance(message.get("from"), dict) else None,
        )

        await self._emit_processing_signal(
            chat_id=room_id,
            message_id=message_id,
            state=PROCESSING_STATE_START,
        )
        try:
            message_responses: list[dict] | None = []
            text = message.get("text")
            if isinstance(text, str):
                message_context = None
                if text.startswith("/"):
                    message_context = [
                        {
                            "type": "telegram_command",
                            "content": {
                                "command": text.split(maxsplit=1)[0],
                            },
                        }
                    ]
                message_responses = await self._messaging_service.handle_text_message(
                    "telegram",
                    room_id=room_id,
                    sender=sender,
                    message=text,
                    message_context=self._compose_message_context(
                        ingress_route=ingress_route,
                        extra_context=message_context,
                    ),
                )
            elif isinstance(message.get("audio"), dict):
                file_id = message["audio"].get("file_id")
                if isinstance(file_id, str) and file_id != "":
                    media = await self._download_message_media(file_id=file_id)
                    if media is not None:
                        message_responses = await self._messaging_service.handle_audio_message(
                            "telegram",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": message,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            elif isinstance(message.get("document"), dict):
                file_id = message["document"].get("file_id")
                if isinstance(file_id, str) and file_id != "":
                    media = await self._download_message_media(file_id=file_id)
                    if media is not None:
                        message_responses = await self._messaging_service.handle_file_message(
                            "telegram",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": message,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            elif isinstance(message.get("photo"), list) and message["photo"]:
                photo_candidates = [item for item in message["photo"] if isinstance(item, dict)]
                if photo_candidates:
                    best_photo = max(
                        photo_candidates,
                        key=lambda item: int(item.get("file_size", 0) or 0),
                    )
                    file_id = best_photo.get("file_id")
                    if isinstance(file_id, str) and file_id != "":
                        media = await self._download_message_media(file_id=file_id)
                        if media is not None:
                            message_responses = await self._messaging_service.handle_image_message(
                                "telegram",
                                room_id=room_id,
                                sender=sender,
                                message=self._merge_ingress_metadata(
                                    payload={
                                        "message": message,
                                        **media,
                                    },
                                    ingress_route=ingress_route,
                                ),
                            )
            elif isinstance(message.get("video"), dict):
                file_id = message["video"].get("file_id")
                if isinstance(file_id, str) and file_id != "":
                    media = await self._download_message_media(file_id=file_id)
                    if media is not None:
                        message_responses = await self._messaging_service.handle_video_message(
                            "telegram",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": message,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            else:
                self._logging_gateway.debug(
                    "Unsupported Telegram message payload type."
                )

            for response in message_responses or []:
                await self._send_response_to_user(response, room_id)
        finally:
            await self._emit_processing_signal(
                chat_id=room_id,
                message_id=message_id,
                state=PROCESSING_STATE_STOP,
            )

    async def _handle_callback_query_update(
        self,
        update: dict,
        callback_query: dict,
        ingress_route: dict[str, Any] | None = None,
        *,
        skip_dedupe: bool = False,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        callback_query_id = callback_query.get("id")
        if isinstance(callback_query_id, str) and callback_query_id.strip() != "":
            # Ack quickly before downstream processing.
            await self._client.answer_callback_query(callback_query_id=callback_query_id)

        if (
            skip_dedupe is not True
            and await self._is_duplicate_event("callback_query", callback_query)
        ):
            self._logging_gateway.debug("Skip duplicate Telegram callback event.")
            return

        callback_message = callback_query.get("message")
        if not isinstance(callback_message, dict):
            self._logging_gateway.error("Malformed Telegram callback payload.")
            return

        chat = callback_message.get("chat")
        chat_type = chat.get("type") if isinstance(chat, dict) else None
        if chat_type != "private":
            self._logging_gateway.info(
                "Ignoring non-private Telegram callback "
                f"chat_type={chat_type!r} update_id={update.get('update_id')!r}."
            )
            return

        room_id = self._coerce_chat_id(chat.get("id") if isinstance(chat, dict) else None)
        sender = self._coerce_user_id(
            callback_query.get("from", {}).get("id")
            if isinstance(callback_query.get("from"), dict)
            else None
        )
        if not isinstance(room_id, str) or not isinstance(sender, str):
            self._logging_gateway.error("Malformed Telegram callback payload.")
            return

        callback_data = callback_query.get("data")
        if not isinstance(callback_data, str):
            self._logging_gateway.error("Telegram callback payload missing data field.")
            return

        message_id = callback_message.get("message_id")
        if message_id is not None:
            message_id = str(message_id)

        await self._register_sender_if_unknown(
            sender=sender,
            room_id=room_id,
            user_obj=(
                callback_query.get("from")
                if isinstance(callback_query.get("from"), dict)
                else None
            ),
        )

        await self._emit_processing_signal(
            chat_id=room_id,
            message_id=message_id,
            state=PROCESSING_STATE_START,
        )
        try:
            responses = await self._messaging_service.handle_text_message(
                "telegram",
                room_id=room_id,
                sender=sender,
                message=callback_data,
                message_context=self._compose_message_context(
                    ingress_route=ingress_route,
                    extra_context=[
                        {
                            "type": "telegram_callback",
                            "content": {
                                "callback_query_id": callback_query_id,
                                "callback_data": callback_data,
                            },
                        }
                    ],
                ),
            )
            for response in responses or []:
                await self._send_response_to_user(response, room_id)
        finally:
            await self._emit_processing_signal(
                chat_id=room_id,
                message_id=message_id,
                state=PROCESSING_STATE_STOP,
            )

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        self._logging_gateway.debug(
            "TelegramBotAPIIPCExtension: Executing command:"
            f" {request.command}"
        )
        match request.command:
            case "telegram_ingress_event":
                await self._telegram_ingress_event(request)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case "telegram_botapi_update":
                await self._telegram_botapi_update(request)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case _:
                return IPCHandlerResult(
                    handler=handler_name,
                    ok=False,
                    code="not_found",
                    error="Unsupported IPC command.",
                )

    async def _telegram_ingress_event(self, request: IPCCommandRequest) -> None:
        payload = request.data if isinstance(request.data, dict) else {}
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            raise TypeError("Telegram ingress payload.event must be a dict.")

        provider_context = payload.get("provider_context")
        provider_context = provider_context if isinstance(provider_context, dict) else {}
        ingress_route = self._normalize_ingress_route(provider_context.get("ingress_route"))
        path_token = self._coerce_nonempty_string(provider_context.get("path_token"))
        if ingress_route.get("runtime_profile_key") in [None, ""] and path_token is not None:
            resolved = await self._resolve_ingress_route(
                path_token=path_token,
                webhook_payload=event_payload,
            )
            if resolved is not None:
                ingress_route = resolved

        runtime_profile_key = self._coerce_nonempty_string(
            payload.get("runtime_profile_key")
        ) or runtime_profile_key_from_ingress_route(ingress_route)
        update = (
            event_payload.get("update")
            if isinstance(event_payload.get("update"), dict)
            else event_payload
        )

        with runtime_profile_scope(runtime_profile_key):
            message = event_payload.get("message")
            if isinstance(message, dict):
                await self._handle_message_update(
                    update,
                    message,
                    ingress_route,
                    skip_dedupe=True,
                )

            callback_query = event_payload.get("callback_query")
            if isinstance(callback_query, dict):
                await self._handle_callback_query_update(
                    update,
                    callback_query,
                    ingress_route,
                    skip_dedupe=True,
                )

    async def _telegram_botapi_update(self, request: IPCCommandRequest) -> None:
        """Process Telegram Bot API update payload."""
        started = time.perf_counter()
        event_payload = request.data if isinstance(request.data, dict) else {}
        try:
            update = request.data
            if not isinstance(update, dict):
                raise TypeError
            path_token = self._coerce_nonempty_string(update.get("path_token"))
            if isinstance(update.get("payload"), dict):
                update = update.get("payload")

            ingress_route = await self._resolve_ingress_route(
                path_token=path_token,
                webhook_payload=event_payload,
            )
            if ingress_route is None:
                return

            with runtime_profile_scope(
                runtime_profile_key_from_ingress_route(ingress_route)
            ):
                handled = False
                message = update.get("message")
                if isinstance(message, dict):
                    handled = True
                    await self._handle_message_update(
                        update,
                        message,
                        ingress_route,
                    )

                callback_query = update.get("callback_query")
                if isinstance(callback_query, dict):
                    handled = True
                    await self._handle_callback_query_update(
                        update,
                        callback_query,
                        ingress_route,
                    )

                if handled is not True:
                    self._logging_gateway.debug("Unsupported Telegram update payload.")
        except (KeyError, TypeError):
            self._increment_metric("telegram.ipc.event.malformed")
            self._logging_gateway.error("Malformed Telegram update payload.")
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=event_payload,
                reason_code="malformed_payload",
                error_message="Malformed Telegram update payload.",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._increment_metric("telegram.ipc.event.processed_failed")
            self._logging_gateway.error(
                "Unhandled Telegram update processing failure."
                f" error={type(exc).__name__}: {exc}"
            )
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=event_payload,
                reason_code="processing_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        else:
            self._increment_metric("telegram.ipc.event.processed_ok")
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"Telegram webhook update processing latency_ms={latency_ms:.2f}."
            )
