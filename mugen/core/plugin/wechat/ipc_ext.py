"""Provides an implementation of IIPCExtension for WeChat support."""

__all__ = ["WeChatIPCExtension"]

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.client.wechat import IWeChatClient
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
from mugen.core.service.ingress_routing import (
    DefaultIngressRoutingService,
)
from mugen.core.utility.config_value import parse_bool_flag
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    normalize_processing_state,
)


def _wechat_client_provider():
    return di.container.wechat_client


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


class WeChatIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WeChat support."""

    _event_dedup_table = "wechat_event_dedup"
    _event_dead_letter_table = "wechat_event_dead_letter"
    _default_event_dedup_ttl_seconds = 86400

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        relational_storage_gateway: IRelationalStorageGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
        wechat_client: IWeChatClient | None = None,
        ingress_routing_service: IIngressRoutingService | None = None,
    ) -> None:
        self._client = wechat_client if wechat_client is not None else _wechat_client_provider()
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
        self._user_service = user_service if user_service is not None else _user_service_provider()
        self._ingress_routing_service = ingress_routing_service
        self._event_dedup_ttl_seconds = self._resolve_event_dedup_ttl_seconds()
        self._typing_enabled = self._resolve_typing_enabled()

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "wechat_official_account_event",
            "wechat_wecom_event",
        ]

    @property
    def platforms(self) -> list[str]:
        return ["wechat"]

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "wechat", SimpleNamespace()), "webhook", None),
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
            getattr(getattr(self._config, "wechat", SimpleNamespace()), "typing", None),
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

    @staticmethod
    def _build_event_dedupe_key(event_type: str, event_payload: dict) -> str:
        payload_for_hash = event_payload
        if isinstance(event_payload, dict):
            # Exclude ingress-local observability metadata from dedupe identity.
            payload_for_hash = {
                key: value
                for key, value in event_payload.items()
                if key != "_received_at"
            }
        payload = json.dumps(payload_for_hash, sort_keys=True, separators=(",", ":"))
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
        except SQLAlchemyError as exc:
            self._logging_gateway.error(
                "Failed to write WeChat dead-letter event. "
                f"reason_code={reason_code} error={type(exc).__name__}: {exc}"
            )

    async def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        event_id = event_payload.get("event_id")
        if event_id is None:
            event_id = event_payload.get("MsgId")
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
                    "expires_at": now + timedelta(seconds=self._event_dedup_ttl_seconds),
                },
            )
            return False
        except IntegrityError:
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
            self._logging_gateway.error(
                "WeChat dedupe lookup failed. "
                f"error={type(exc).__name__}: {exc}"
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
            "platform": "wechat",
            "channel_key": "wechat",
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
                platform="wechat",
                channel_key="wechat",
                identifier_type="path_token",
                identifier_value=path_token,
                claims=claims,
            )
        )
        try:
            ingress_route = resolve_ingress_route_context(
                platform="wechat",
                channel_key="wechat",
                routing=resolution,
                source="wechat.ingress_routing",
                identifier_claims=claims,
                global_fallback_reasons=(),
            )
        except ContextScopeResolutionError as exc:
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=webhook_payload,
                reason_code="route_unresolved",
                error_message=str(exc),
            )
            self._logging_gateway.warning(
                "Dropped WeChat webhook due to unresolved ingress route "
                f"reason_code={exc.reason_code} path_token={path_token!r}."
            )
            return None
        return ingress_route

    async def _emit_processing_signal(
        self,
        *,
        recipient: str,
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
            await emitter(
                recipient,
                state=normalized_state,
                message_id=message_id,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "WeChat thinking signal raised unexpectedly "
                f"(recipient={recipient} state={state}): {exc}"
            )

    async def _register_sender_if_unknown(self, *, sender: str, room_id: str) -> None:
        known_users = await self._user_service.get_known_users_list()
        known_users = known_users if isinstance(known_users, dict) else {}
        if sender in known_users:
            return
        self._logging_gateway.debug(f"New WeChat contact: {sender}")
        await self._user_service.add_known_user(sender, sender, room_id)

    async def _download_message_media(self, *, media_id: str) -> dict | None:
        downloaded = await self._client.download_media(media_id=media_id)
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

    async def _upload_response_media(self, response: dict, context: str) -> dict | None:
        file_data = response.get("file")
        if not isinstance(file_data, dict):
            self._logging_gateway.error(f"Missing file payload for {context} response.")
            return None

        media_id = self._coerce_nonempty_string(file_data.get("id"))
        if media_id is None:
            media_id = self._coerce_nonempty_string(file_data.get("media_id"))
        if media_id is not None:
            return {"media_id": media_id, "file": file_data}

        uri = self._coerce_nonempty_string(file_data.get("uri"))
        content_type = self._coerce_nonempty_string(file_data.get("type"))
        if uri is None or content_type is None:
            self._logging_gateway.error(f"Invalid file payload for {context} response.")
            return None

        upload_response = await self._client.upload_media(
            file_path=uri,
            media_type=content_type,
        )
        if not isinstance(upload_response, dict):
            return None
        upload_data = upload_response.get("data")
        if not isinstance(upload_data, dict):
            return None

        media_id = self._coerce_nonempty_string(upload_data.get("media_id"))
        if media_id is None:
            media_id = self._coerce_nonempty_string(upload_data.get("id"))
        if media_id is None:
            self._logging_gateway.error(f"{context} upload did not return media id.")
            return None

        return {
            "media_id": media_id,
            "file": file_data,
        }

    async def _send_response_to_user(self, response: dict, recipient: str) -> None:
        response_type = response.get("type")

        if response_type == "wechat":
            op = str(response.get("op") or "").strip().lower()
            if op == "send_raw":
                payload = response.get("content")
                if not isinstance(payload, dict):
                    self._logging_gateway.error("Missing WeChat raw payload.")
                    return
                await self._client.send_raw_message(payload=payload)
                return
            if op == "send_message":
                text = response.get("text")
                if not isinstance(text, str):
                    self._logging_gateway.error("Missing WeChat send_message text payload.")
                    return
                await self._client.send_text_message(
                    recipient=recipient,
                    text=text,
                )
                return
            self._logging_gateway.error(f"Unsupported WeChat response op: {op}.")
            return

        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str):
                self._logging_gateway.error("Missing text content in response payload.")
                return
            await self._client.send_text_message(
                recipient=recipient,
                text=content,
            )
            return

        if response_type == "audio":
            uploaded = await self._upload_response_media(response, "audio")
            if uploaded is None:
                return
            await self._client.send_audio_message(
                recipient=recipient,
                audio={"media_id": uploaded["media_id"]},
            )
            return

        if response_type == "file":
            uploaded = await self._upload_response_media(response, "file")
            if uploaded is None:
                return
            await self._client.send_file_message(
                recipient=recipient,
                file={"media_id": uploaded["media_id"]},
            )
            return

        if response_type == "image":
            uploaded = await self._upload_response_media(response, "image")
            if uploaded is None:
                return
            await self._client.send_image_message(
                recipient=recipient,
                image={"media_id": uploaded["media_id"]},
            )
            return

        if response_type == "video":
            uploaded = await self._upload_response_media(response, "video")
            if uploaded is None:
                return
            await self._client.send_video_message(
                recipient=recipient,
                video={"media_id": uploaded["media_id"]},
            )
            return

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")

    async def _process_inbound_message(
        self,
        *,
        provider: str,
        payload: dict,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        event_type = f"{provider}:event"
        if await self._is_duplicate_event(event_type, payload):
            self._logging_gateway.debug("Skip duplicate WeChat event.")
            return

        sender = self._coerce_nonempty_string(payload.get("FromUserName"))
        room_id = sender
        if sender is None or room_id is None:
            self._logging_gateway.error("Malformed WeChat event payload.")
            return

        message_id = self._coerce_nonempty_string(payload.get("MsgId"))

        await self._register_sender_if_unknown(sender=sender, room_id=room_id)

        msg_type = str(payload.get("MsgType") or "").strip().lower()
        await self._emit_processing_signal(
            recipient=room_id,
            message_id=message_id,
            state=PROCESSING_STATE_START,
        )
        try:
            responses: list[dict] | None = []
            if msg_type == "text":
                text = self._coerce_nonempty_string(payload.get("Content"))
                if text is not None:
                    responses = await self._messaging_service.handle_text_message(
                        "wechat",
                        room_id=room_id,
                        sender=sender,
                        message=text,
                        message_context=self._compose_message_context(
                            ingress_route=ingress_route,
                        ),
                    )
            elif msg_type in {"voice", "audio"}:
                media_id = self._coerce_nonempty_string(payload.get("MediaId"))
                if media_id is not None:
                    media = await self._download_message_media(media_id=media_id)
                    if media is not None:
                        responses = await self._messaging_service.handle_audio_message(
                            "wechat",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": payload,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            elif msg_type in {"image"}:
                media_id = self._coerce_nonempty_string(payload.get("MediaId"))
                if media_id is not None:
                    media = await self._download_message_media(media_id=media_id)
                    if media is not None:
                        responses = await self._messaging_service.handle_image_message(
                            "wechat",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": payload,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            elif msg_type in {"video", "shortvideo"}:
                media_id = self._coerce_nonempty_string(payload.get("MediaId"))
                if media_id is not None:
                    media = await self._download_message_media(media_id=media_id)
                    if media is not None:
                        responses = await self._messaging_service.handle_video_message(
                            "wechat",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": payload,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            elif msg_type == "file":
                media_id = self._coerce_nonempty_string(payload.get("MediaId"))
                if media_id is not None:
                    media = await self._download_message_media(media_id=media_id)
                    if media is not None:
                        responses = await self._messaging_service.handle_file_message(
                            "wechat",
                            room_id=room_id,
                            sender=sender,
                            message=self._merge_ingress_metadata(
                                payload={
                                    "message": payload,
                                    **media,
                                },
                                ingress_route=ingress_route,
                            ),
                        )
            else:
                self._logging_gateway.debug(
                    f"Unsupported WeChat message type: {msg_type}."
                )

            for response in responses or []:
                await self._send_response_to_user(response, room_id)
        finally:
            await self._emit_processing_signal(
                recipient=room_id,
                message_id=message_id,
                state=PROCESSING_STATE_STOP,
            )

    async def _wechat_event(
        self,
        request: IPCCommandRequest,
        *,
        expected_provider: str,
    ) -> None:
        started = time.perf_counter()
        event_payload = request.data if isinstance(request.data, dict) else {}
        try:
            data = request.data
            if not isinstance(data, dict):
                raise TypeError

            provider = str(data.get("provider") or "").strip().lower()
            if provider != expected_provider:
                raise ValueError("provider_mismatch")
            path_token = self._coerce_nonempty_string(data.get("path_token"))

            payload = data.get("payload")
            if not isinstance(payload, dict):
                raise TypeError

            ingress_route = await self._resolve_ingress_route(
                path_token=path_token,
                webhook_payload=event_payload,
            )
            if ingress_route is None:
                return

            await self._process_inbound_message(
                provider=provider,
                payload=payload,
                ingress_route=ingress_route,
            )
        except (KeyError, TypeError):
            self._logging_gateway.error("Malformed WeChat event payload.")
            await self._record_dead_letter(
                event_type=f"{expected_provider}:webhook",
                event_payload=event_payload,
                reason_code="malformed_payload",
                error_message="Malformed WeChat event payload.",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Unhandled WeChat event processing failure "
                f"error={type(exc).__name__}: {exc}"
            )
            await self._record_dead_letter(
                event_type=f"{expected_provider}:webhook",
                event_payload=event_payload,
                reason_code="processing_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"WeChat webhook event processing latency_ms={latency_ms:.2f}."
            )

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__

        match request.command:
            case "wechat_official_account_event":
                await self._wechat_event(request, expected_provider="official_account")
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case "wechat_wecom_event":
                await self._wechat_event(request, expected_provider="wecom")
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
