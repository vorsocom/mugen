"""Provides an implementation of IIPCExtension for LINE Messaging API support."""

__all__ = ["LineMessagingAPIIPCExtension"]

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core import di
from mugen.core.contract.client.line import ILineClient
from mugen.core.contract.extension.ipc import IIPCExtension
from mugen.core.contract.extension.mh import IMHExtension
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway
from mugen.core.contract.service.ingress_routing import (
    IIngressRoutingService,
    IngressRouteRequest,
)
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult
from mugen.core.contract.service.messaging import IMessagingService
from mugen.core.contract.service.user import IUserService
from mugen.core.service.context_scope_resolution import (
    ContextScopeResolutionError,
    context_scope_from_ingress_route,
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


def _line_client_provider():
    return di.container.line_client


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


class LineMessagingAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for LINE Messaging API support."""

    _event_dedup_table = "line_messagingapi_event_dedup"
    _event_dead_letter_table = "line_messagingapi_event_dead_letter"
    _default_event_dedup_ttl_seconds = 86400
    _max_messages_per_request = 5

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        relational_storage_gateway: IRelationalStorageGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
        line_client: ILineClient | None = None,
        ingress_routing_service: IIngressRoutingService | None = None,
    ) -> None:
        self._client = line_client if line_client is not None else _line_client_provider()
        self._config = config if config is not None else _config_provider()
        self._logging_gateway = (
            logging_gateway if logging_gateway is not None else _logging_gateway_provider()
        )
        self._relational_storage_gateway = (
            relational_storage_gateway
            if relational_storage_gateway is not None
            else _relational_storage_gateway_provider()
        )
        self._messaging_service = (
            messaging_service if messaging_service is not None else _messaging_service_provider()
        )
        self._user_service = user_service if user_service is not None else _user_service_provider()
        self._ingress_routing_service = ingress_routing_service
        self._event_dedup_ttl_seconds = self._resolve_event_dedup_ttl_seconds()
        self._typing_enabled = self._resolve_typing_enabled()
        self._metrics: dict[str, int] = {}

    @property
    def ipc_commands(self) -> list[str]:
        return ["line_ingress_event", "line_messagingapi_event"]

    @property
    def platforms(self) -> list[str]:
        return ["line"]

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "line", SimpleNamespace()), "webhook", None),
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
            getattr(getattr(self._config, "line", SimpleNamespace()), "typing", None),
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
            self._increment_metric("line.ipc.dead_letter.write_success")
        except SQLAlchemyError as exc:
            self._increment_metric("line.ipc.dead_letter.write_failure")
            self._logging_gateway.error(
                "Failed to write LINE dead-letter event."
                f" reason_code={reason_code}"
                f" error={type(exc).__name__}: {exc}"
            )

    async def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        event_id = self._coerce_nonempty_string(event_payload.get("webhookEventId"))
        message = event_payload.get("message")
        if event_id is None and isinstance(message, dict):
            event_id = self._coerce_nonempty_string(message.get("id"))

        now = self._now_utc()
        try:
            await self._relational_storage_gateway.insert_one(
                self._event_dedup_table,
                {
                    "event_type": event_type,
                    "dedupe_key": dedupe_key,
                    "event_id": event_id,
                    "last_seen_at": now,
                    "expires_at": now + timedelta(seconds=self._event_dedup_ttl_seconds),
                },
            )
            self._increment_metric("line.ipc.dedupe.miss")
            return False
        except IntegrityError:
            self._increment_metric("line.ipc.dedupe.hit")
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
            self._increment_metric("line.ipc.dedupe.error")
            self._logging_gateway.error(
                "LINE dedupe lookup failed."
                f" error={type(exc).__name__}: {exc}"
            )
            return False

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
            "platform": "line",
            "channel_key": "line",
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
                platform="line",
                channel_key="line",
                identifier_type="path_token",
                identifier_value=path_token,
                claims=claims,
            )
        )
        try:
            ingress_route = resolve_ingress_route_context(
                platform="line",
                channel_key="line",
                routing=resolution,
                source="line.ingress_routing",
                identifier_claims=claims,
                global_fallback_reasons=(),
            )
        except ContextScopeResolutionError as exc:
            self._increment_metric("line.ipc.route.unresolved")
            reason_code = str(exc.reason_code or "route_unresolved")
            error_message = str(exc)
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=webhook_payload,
                reason_code="route_unresolved",
                error_message=error_message,
            )
            self._logging_gateway.warning(
                "Dropped LINE webhook due to unresolved ingress route "
                f"reason_code={reason_code} path_token={path_token!r}."
            )
            return None
        return ingress_route

    @staticmethod
    def _api_call_succeeded(response: dict | None) -> bool:
        if not isinstance(response, dict):
            return False
        if response.get("ok") is not True:
            return False
        status = response.get("status")
        if status is None:
            return True
        if not isinstance(status, int):
            return False
        return 200 <= status < 300

    @staticmethod
    def _split_message_batches(messages: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for message in messages:
            current.append(message)
            if len(current) >= batch_size:
                batches.append(current)
                current = []
        if current:
            batches.append(current)
        return batches

    async def _push_message_batches(
        self,
        *,
        recipient: str,
        messages: list[dict[str, Any]],
    ) -> None:
        for batch in self._split_message_batches(messages, self._max_messages_per_request):
            response = await self._client.push_messages(
                to=recipient,
                messages=batch,
            )
            if self._api_call_succeeded(response):
                continue
            self._logging_gateway.warning(
                "LINE push batch delivery failed "
                f"recipient={recipient} response={response}."
            )

    async def _reply_or_push_messages(
        self,
        *,
        recipient: str,
        reply_token: str | None,
        messages: list[dict[str, Any]],
    ) -> bool:
        if not messages:
            return False

        batches = self._split_message_batches(messages, self._max_messages_per_request)
        if not batches:
            return False

        used_reply_token = False
        if isinstance(reply_token, str) and reply_token.strip() != "":
            first_batch = batches[0]
            reply_response = await self._client.reply_messages(
                reply_token=reply_token.strip(),
                messages=first_batch,
            )
            used_reply_token = True
            if not self._api_call_succeeded(reply_response):
                self._logging_gateway.warning(
                    "LINE reply delivery failed, falling back to push "
                    f"recipient={recipient} response={reply_response}."
                )
                await self._push_message_batches(
                    recipient=recipient,
                    messages=first_batch,
                )
            batches = batches[1:]

        for batch in batches:
            push_response = await self._client.push_messages(
                to=recipient,
                messages=batch,
            )
            if self._api_call_succeeded(push_response):
                continue
            self._logging_gateway.warning(
                "LINE push delivery failed "
                f"recipient={recipient} response={push_response}."
            )

        return used_reply_token

    @staticmethod
    def _is_https_url(value: object) -> bool:
        return isinstance(value, str) and value.strip().startswith("https://")

    def _line_message_from_response(self, response: dict) -> dict[str, Any] | None:
        response_type = response.get("type")

        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str):
                self._logging_gateway.error("Missing text content in response payload.")
                return None
            return {
                "type": "text",
                "text": content,
            }

        file_data = response.get("file")
        if response_type in {"audio", "file", "image", "video"} and not isinstance(
            file_data, dict
        ):
            self._logging_gateway.error(f"Missing {response_type} payload in response.")
            return None

        if response_type == "audio":
            url = file_data.get("url", file_data.get("uri"))
            if self._is_https_url(url) is not True:
                self._logging_gateway.warning(
                    "Reject LINE audio response with non-HTTPS media URL."
                )
                return None
            duration = file_data.get("duration")
            if not isinstance(duration, int) or duration <= 0:
                duration = 1000
            return {
                "type": "audio",
                "originalContentUrl": url.strip(),
                "duration": duration,
            }

        if response_type == "image":
            url = file_data.get("url", file_data.get("uri"))
            preview_url = file_data.get(
                "preview_url",
                file_data.get("preview_image_url", url),
            )
            if self._is_https_url(url) is not True or self._is_https_url(preview_url) is not True:
                self._logging_gateway.warning(
                    "Reject LINE image response with non-HTTPS media URL."
                )
                return None
            return {
                "type": "image",
                "originalContentUrl": url.strip(),
                "previewImageUrl": preview_url.strip(),
            }

        if response_type == "video":
            url = file_data.get("url", file_data.get("uri"))
            preview_url = file_data.get(
                "preview_url",
                file_data.get("preview_image_url", url),
            )
            if self._is_https_url(url) is not True or self._is_https_url(preview_url) is not True:
                self._logging_gateway.warning(
                    "Reject LINE video response with non-HTTPS media URL."
                )
                return None
            return {
                "type": "video",
                "originalContentUrl": url.strip(),
                "previewImageUrl": preview_url.strip(),
            }

        if response_type == "file":
            url = file_data.get("url", file_data.get("uri"))
            if self._is_https_url(url) is not True:
                self._logging_gateway.warning(
                    "Reject LINE file response with non-HTTPS media URL."
                )
                return None
            file_name = self._coerce_nonempty_string(file_data.get("name"))
            if file_name is None:
                text = url.strip()
            else:
                text = f"{file_name}: {url.strip()}"
            return {
                "type": "text",
                "text": text,
            }

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")
        return None

    async def _handle_line_envelope_response(
        self,
        *,
        response: dict,
        sender: str,
        fallback_reply_token: str | None,
    ) -> bool:
        op = str(response.get("op") or "").strip().lower()
        payload = response.get("payload")
        if not isinstance(payload, dict):
            payload = response

        if op == "reply":
            messages = payload.get("messages")
            if not isinstance(messages, list):
                self._logging_gateway.error("LINE reply op requires messages list.")
                return False

            reply_token = self._coerce_nonempty_string(
                payload.get("reply_token", payload.get("replyToken"))
            )
            if reply_token is None:
                reply_token = self._coerce_nonempty_string(fallback_reply_token)

            if reply_token is None:
                self._logging_gateway.warning(
                    "LINE reply op missing usable reply token; falling back to push."
                )
                await self._push_message_batches(recipient=sender, messages=messages)
                return False

            reply_response = await self._client.reply_messages(
                reply_token=reply_token,
                messages=messages,
            )
            if self._api_call_succeeded(reply_response):
                return True

            self._logging_gateway.warning(
                "LINE reply op failed; falling back to push "
                f"sender={sender} response={reply_response}."
            )
            await self._push_message_batches(recipient=sender, messages=messages)
            return True

        if op == "push":
            recipient = self._coerce_nonempty_string(payload.get("to"))
            if recipient is None:
                recipient = sender
            messages = payload.get("messages")
            if not isinstance(messages, list):
                self._logging_gateway.error("LINE push op requires messages list.")
                return False
            await self._push_message_batches(recipient=recipient, messages=messages)
            return False

        if op == "multicast":
            recipients = payload.get("to")
            messages = payload.get("messages")
            if not isinstance(recipients, list):
                self._logging_gateway.error(
                    "LINE multicast op requires recipient list."
                )
                return False
            if not isinstance(messages, list):
                self._logging_gateway.error("LINE multicast op requires messages list.")
                return False
            multicast_response = await self._client.multicast_messages(
                to=recipients,
                messages=messages,
            )
            if self._api_call_succeeded(multicast_response):
                return False
            self._logging_gateway.warning(
                "LINE multicast delivery failed "
                f"response={multicast_response}."
            )
            return False

        self._logging_gateway.error(f"Unsupported LINE response op: {op}.")
        return False

    async def _dispatch_message_responses(
        self,
        *,
        responses: list[dict] | None,
        sender: str,
        reply_token: str | None,
    ) -> None:
        normalized_messages: list[dict[str, Any]] = []
        reply_token_consumed = False

        for response in responses or []:
            if not isinstance(response, dict):
                continue

            if response.get("type") == "line":
                consumed = await self._handle_line_envelope_response(
                    response=response,
                    sender=sender,
                    fallback_reply_token=None if reply_token_consumed else reply_token,
                )
                if consumed:
                    reply_token_consumed = True
                continue

            normalized = self._line_message_from_response(response)
            if isinstance(normalized, dict):
                normalized_messages.append(normalized)

        effective_reply_token = None if reply_token_consumed else reply_token
        await self._reply_or_push_messages(
            recipient=sender,
            reply_token=effective_reply_token,
            messages=normalized_messages,
        )

    async def _emit_processing_signal(
        self,
        *,
        sender: str,
        message_id: str | None,
        state: str,
    ) -> None:
        if self._typing_enabled is not True:
            return

        emitter = getattr(self._client, "emit_processing_signal", None)
        if not callable(emitter):
            return

        try:
            normalized_state = normalize_processing_state(state)
            result = await emitter(
                sender,
                state=normalized_state,
                message_id=message_id,
            )
            if result is False:
                self._logging_gateway.warning(
                    "LINE processing signal reported failure "
                    f"(sender={sender} state={normalized_state})."
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "LINE processing signal raised unexpectedly "
                f"(sender={sender} state={state}): {exc}"
            )

    async def _register_sender_if_unknown(self, *, sender: str) -> None:
        known_users = await self._user_service.get_known_users_list()
        known_users = known_users if isinstance(known_users, dict) else {}
        if sender in known_users:
            return

        display_name = sender
        try:
            profile = await self._client.get_profile(user_id=sender)
        except Exception:  # pylint: disable=broad-exception-caught
            profile = None
        if isinstance(profile, dict):
            profile_data = profile.get("data")
            if isinstance(profile_data, dict):
                profile_name = self._coerce_nonempty_string(
                    profile_data.get("displayName")
                )
                if profile_name is not None:
                    display_name = profile_name

        self._logging_gateway.debug(f"New LINE contact: {sender}")
        await self._user_service.add_known_user(sender, display_name, sender)

    async def _download_message_media(self, *, message: dict) -> dict[str, Any] | None:
        message_id = self._coerce_nonempty_string(message.get("id"))
        if message_id is None:
            self._logging_gateway.error("Malformed LINE media payload: missing id.")
            return None

        downloaded = await self._client.download_media(message_id=message_id)
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

    async def _call_message_handlers(
        self,
        *,
        message: dict,
        message_type: str,
        sender: str,
        message_context: list[dict] | None = None,
    ) -> None:
        ingress_route = None
        for item in message_context or []:
            if item.get("type") != "ingress_route":
                continue
            content = item.get("content")
            if isinstance(content, dict):
                ingress_route = dict(content)
                break
        resolved = context_scope_from_ingress_route(
            platform="line",
            channel_key="line",
            room_id=sender,
            sender_id=sender,
            ingress_route=ingress_route,
            source="line.ipc_extension",
        )
        hits = 0
        message_handlers: list[IMHExtension] = self._messaging_service.mh_extensions
        for handler in message_handlers:
            if (
                handler.platform_supported("line")
                and message_type in handler.message_types
            ):
                await handler.handle_message(
                    platform="line",
                    room_id=sender,
                    sender=sender,
                    message=message,
                    message_context=message_context,
                    ingress_metadata={
                        "ingress_route": dict(resolved.ingress_route),
                        "tenant_resolution": dict(resolved.tenant_resolution),
                    },
                    scope=resolved.scope,
                )
                hits += 1

        if hits == 0:
            self._logging_gateway.debug(f"Unsupported LINE event type: {message_type}.")

    async def _handle_message_event(
        self,
        *,
        event: dict,
        sender: str,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        message = event.get("message")
        if not isinstance(message, dict):
            self._logging_gateway.error("Malformed LINE message payload.")
            return

        message_type = self._coerce_nonempty_string(message.get("type"))
        if message_type is None:
            self._logging_gateway.error("Malformed LINE message payload.")
            return

        message_id = self._coerce_nonempty_string(message.get("id"))
        reply_token = self._coerce_nonempty_string(event.get("replyToken"))

        await self._register_sender_if_unknown(sender=sender)
        await self._emit_processing_signal(
            sender=sender,
            message_id=message_id,
            state=PROCESSING_STATE_START,
        )
        try:
            responses: list[dict] | None = []
            if message_type == "text":
                text = message.get("text")
                if not isinstance(text, str):
                    self._logging_gateway.error("Malformed LINE text message payload.")
                    return
                responses = await self._messaging_service.handle_text_message(
                    "line",
                    room_id=sender,
                    sender=sender,
                    message=text,
                    message_context=self._compose_message_context(
                        ingress_route=ingress_route,
                    ),
                )
            elif message_type == "audio":
                media = await self._download_message_media(message=message)
                if media is not None:
                    responses = await self._messaging_service.handle_audio_message(
                        "line",
                        room_id=sender,
                        sender=sender,
                        message=self._merge_ingress_metadata(
                            payload={
                                "message": message,
                                **media,
                            },
                            ingress_route=ingress_route,
                        ),
                    )
            elif message_type == "file":
                media = await self._download_message_media(message=message)
                if media is not None:
                    responses = await self._messaging_service.handle_file_message(
                        "line",
                        room_id=sender,
                        sender=sender,
                        message=self._merge_ingress_metadata(
                            payload={
                                "message": message,
                                **media,
                            },
                            ingress_route=ingress_route,
                        ),
                    )
            elif message_type == "image":
                media = await self._download_message_media(message=message)
                if media is not None:
                    responses = await self._messaging_service.handle_image_message(
                        "line",
                        room_id=sender,
                        sender=sender,
                        message=self._merge_ingress_metadata(
                            payload={
                                "message": message,
                                **media,
                            },
                            ingress_route=ingress_route,
                        ),
                    )
            elif message_type == "video":
                media = await self._download_message_media(message=message)
                if media is not None:
                    responses = await self._messaging_service.handle_video_message(
                        "line",
                        room_id=sender,
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
                await self._call_message_handlers(
                    message=event,
                    message_type=message_type,
                    sender=sender,
                    message_context=self._compose_message_context(
                        ingress_route=ingress_route,
                        extra_context=[
                            {
                                "type": "line_event",
                                "content": {
                                    "event_type": "message",
                                    "message_type": message_type,
                                },
                            }
                        ],
                    ),
                )
                return

            await self._dispatch_message_responses(
                responses=responses,
                sender=sender,
                reply_token=reply_token,
            )
        finally:
            await self._emit_processing_signal(
                sender=sender,
                message_id=message_id,
                state=PROCESSING_STATE_STOP,
            )

    async def _handle_postback_event(
        self,
        *,
        event: dict,
        sender: str,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        reply_token = self._coerce_nonempty_string(event.get("replyToken"))
        postback = event.get("postback")
        if not isinstance(postback, dict):
            self._logging_gateway.error("Malformed LINE postback payload.")
            return

        data = postback.get("data")
        if not isinstance(data, str):
            params = postback.get("params")
            if isinstance(params, dict):
                data = json.dumps(params, sort_keys=True)
            else:
                self._logging_gateway.error("LINE postback payload missing data field.")
                return

        await self._register_sender_if_unknown(sender=sender)
        await self._emit_processing_signal(
            sender=sender,
            message_id=None,
            state=PROCESSING_STATE_START,
        )
        try:
            responses = await self._messaging_service.handle_text_message(
                "line",
                room_id=sender,
                sender=sender,
                message=data,
                message_context=self._compose_message_context(
                    ingress_route=ingress_route,
                    extra_context=[
                        {
                            "type": "line_postback",
                            "content": {
                                "postback": postback,
                            },
                        }
                    ],
                ),
            )
            await self._dispatch_message_responses(
                responses=responses,
                sender=sender,
                reply_token=reply_token,
            )
        finally:
            await self._emit_processing_signal(
                sender=sender,
                message_id=None,
                state=PROCESSING_STATE_STOP,
            )

    async def _handle_lifecycle_event(
        self,
        *,
        event: dict,
        sender: str,
        event_type: str,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        if event_type != "unfollow":
            await self._register_sender_if_unknown(sender=sender)
        await self._call_message_handlers(
            message=event,
            message_type=event_type,
            sender=sender,
            message_context=self._compose_message_context(
                ingress_route=ingress_route,
                extra_context=[
                    {
                        "type": "line_event",
                        "content": {
                            "event_type": event_type,
                        },
                    }
                ],
            ),
        )

    async def _process_single_event(
        self,
        event: dict,
        ingress_route: dict[str, Any] | None = None,
        *,
        skip_dedupe: bool = False,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        source = event.get("source")
        if not isinstance(source, dict):
            self._logging_gateway.error("Malformed LINE event source.")
            return

        source_type = self._coerce_nonempty_string(source.get("type"))
        if source_type != "user":
            self._logging_gateway.info(
                "Ignoring non-user LINE event "
                f"source_type={source_type!r} event_type={event.get('type')!r}."
            )
            return

        sender = self._coerce_nonempty_string(source.get("userId"))
        if sender is None:
            self._logging_gateway.error("Malformed LINE event source.")
            return

        event_type = self._coerce_nonempty_string(event.get("type"))
        if event_type is None:
            self._logging_gateway.error("Malformed LINE event payload.")
            return

        if skip_dedupe is not True and await self._is_duplicate_event(event_type, event):
            self._logging_gateway.debug(
                f"Skip duplicate LINE event type={event_type}."
            )
            return

        if event_type == "message":
            await self._handle_message_event(
                event=event,
                sender=sender,
                ingress_route=ingress_route,
            )
            return

        if event_type == "postback":
            await self._handle_postback_event(
                event=event,
                sender=sender,
                ingress_route=ingress_route,
            )
            return

        if event_type in {"follow", "unfollow", "accountLink", "beacon"}:
            await self._handle_lifecycle_event(
                event=event,
                sender=sender,
                event_type=event_type,
                ingress_route=ingress_route,
            )
            return

        await self._call_message_handlers(
            message=event,
            message_type=event_type,
            sender=sender,
            message_context=self._compose_message_context(
                ingress_route=ingress_route,
                extra_context=[
                    {
                        "type": "line_event",
                        "content": {
                            "event_type": event_type,
                        },
                    }
                ],
            ),
        )

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        self._logging_gateway.debug(
            "LineMessagingAPIIPCExtension: Executing command:"
            f" {request.command}"
        )
        match request.command:
            case "line_ingress_event":
                await self._line_ingress_event(request)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case "line_messagingapi_event":
                await self._line_messagingapi_event(request)
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

    async def _line_ingress_event(self, request: IPCCommandRequest) -> None:
        payload = request.data if isinstance(request.data, dict) else {}
        event = payload.get("payload")
        if not isinstance(event, dict):
            raise TypeError("LINE ingress payload.event must be a dict.")

        provider_context = payload.get("provider_context")
        provider_context = provider_context if isinstance(provider_context, dict) else {}
        ingress_route = self._normalize_ingress_route(provider_context.get("ingress_route"))
        path_token = self._coerce_nonempty_string(provider_context.get("path_token"))
        if ingress_route.get("runtime_profile_key") in [None, ""] and path_token is not None:
            resolved = await self._resolve_ingress_route(
                path_token=path_token,
                webhook_payload=event,
            )
            if resolved is not None:
                ingress_route = resolved

        runtime_profile_key = self._coerce_nonempty_string(
            payload.get("runtime_profile_key")
        ) or runtime_profile_key_from_ingress_route(ingress_route)
        with runtime_profile_scope(runtime_profile_key):
            await self._process_single_event(
                event,
                ingress_route=ingress_route,
                skip_dedupe=True,
            )

    async def _line_messagingapi_event(self, request: IPCCommandRequest) -> None:
        started = time.perf_counter()
        event_payload = request.data if isinstance(request.data, dict) else {}
        try:
            webhook_payload = request.data
            if not isinstance(webhook_payload, dict):
                raise TypeError

            path_token = self._coerce_nonempty_string(webhook_payload.get("path_token"))
            if isinstance(webhook_payload.get("payload"), dict):
                webhook_payload = webhook_payload.get("payload")

            events = webhook_payload.get("events")
            if not isinstance(events, list):
                raise TypeError

            ingress_route = await self._resolve_ingress_route(
                path_token=path_token,
                webhook_payload=event_payload,
            )
            if ingress_route is None:
                return

            with runtime_profile_scope(
                runtime_profile_key_from_ingress_route(ingress_route)
            ):
                for event in events:
                    if not isinstance(event, dict):
                        self._increment_metric("line.ipc.event.malformed")
                        self._logging_gateway.error("Malformed LINE event payload.")
                        await self._record_dead_letter(
                            event_type="event",
                            event_payload={"event": event},
                            reason_code="malformed_payload",
                            error_message="Malformed LINE event payload.",
                        )
                        continue

                    try:
                        await self._process_single_event(
                            event=event,
                            ingress_route=ingress_route,
                        )
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        self._increment_metric("line.ipc.event.processed_failed")
                        self._logging_gateway.error(
                            "Unhandled LINE event processing failure."
                            f" error={type(exc).__name__}: {exc}"
                        )
                        await self._record_dead_letter(
                            event_type=str(event.get("type") or "event"),
                            event_payload=event,
                            reason_code="processing_exception",
                            error_message=f"{type(exc).__name__}: {exc}",
                        )
            self._increment_metric("line.ipc.event.processed_ok")
        except (KeyError, TypeError):
            self._increment_metric("line.ipc.event.malformed")
            self._logging_gateway.error("Malformed LINE webhook payload.")
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=event_payload,
                reason_code="malformed_payload",
                error_message="Malformed LINE webhook payload.",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._increment_metric("line.ipc.event.processed_failed")
            self._logging_gateway.error(
                "Unhandled LINE webhook processing failure."
                f" error={type(exc).__name__}: {exc}"
            )
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=event_payload,
                reason_code="processing_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"LINE webhook event processing latency_ms={latency_ms:.2f}."
            )
