"""Provides an implementation of IIPCExtension for WhatsApp Cloud API support."""

__all__ = ["WhatsAppWACAPIIPCExtension"]

import asyncio
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.client.whatsapp import IWhatsAppClient
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
from mugen.core import di
from mugen.core.service.context_scope_resolution import (
    ContextScopeResolutionError,
    context_scope_from_ingress_route,
    resolve_ingress_route_context,
)
from mugen.core.service.ingress_routing import (
    DefaultIngressRoutingService,
)
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    normalize_processing_state,
)


def _whatsapp_client_provider():
    return di.container.whatsapp_client


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


class WhatsAppWACAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WhatsApp Cloud API support."""

    _event_dedup_table = "whatsapp_wacapi_event_dedup"
    _event_dead_letter_table = "whatsapp_wacapi_event_dead_letter"
    _default_event_dedup_ttl_seconds = 86400

    # pylint: disable=too-many-arguments
    # # pylint: disable=too-many-positional-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        relational_storage_gateway: IRelationalStorageGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
        whatsapp_client: IWhatsAppClient | None = None,
        ingress_routing_service: IIngressRoutingService | None = None,
    ) -> None:
        self._client = (
            whatsapp_client
            if whatsapp_client is not None
            else _whatsapp_client_provider()
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
        self._metrics: dict[str, int] = {}

    @property
    def ipc_commands(self) -> list[str]:
        return [
            "whatsapp_wacapi_event",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["whatsapp"]

    def _ingress_router(self) -> IIngressRoutingService:
        if self._ingress_routing_service is not None:
            return self._ingress_routing_service
        self._ingress_routing_service = DefaultIngressRoutingService(
            relational_storage_gateway=self._relational_storage_gateway,
            logging_gateway=self._logging_gateway,
        )
        return self._ingress_routing_service

    def _extract_api_data(self, payload: dict | None, context: str) -> dict | None:
        if payload is None:
            self._logging_gateway.error(f"Missing payload for {context}.")
            return None

        if not isinstance(payload, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        if payload.get("ok") is not True:
            self._logging_gateway.error(f"{context} failed.")
            error = payload.get("error")
            if error not in [None, ""]:
                self._logging_gateway.error(str(error))
            raw = payload.get("raw")
            if isinstance(raw, str) and raw != "":
                self._logging_gateway.error(raw)
            return None

        data = payload.get("data")
        if data is None:
            return {}

        if not isinstance(data, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        return data

    @staticmethod
    def _extract_user_text(message: dict) -> str | None:
        message_type = message.get("type")

        if message_type == "text":
            text_body = message.get("text", {}).get("body")
            return text_body if isinstance(text_body, str) else None

        if message_type == "button":
            button = message.get("button", {})
            button_text = button.get("text")
            if isinstance(button_text, str) and button_text != "":
                return button_text
            payload = button.get("payload")
            return payload if isinstance(payload, str) else None

        if message_type != "interactive":
            return None

        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "button_reply":
            button_reply = interactive.get("button_reply", {})
            title = button_reply.get("title")
            if isinstance(title, str) and title != "":
                return title
            button_id = button_reply.get("id")
            return button_id if isinstance(button_id, str) else None

        if interactive_type == "list_reply":
            list_reply = interactive.get("list_reply", {})
            title = list_reply.get("title")
            if isinstance(title, str) and title != "":
                return title
            list_id = list_reply.get("id")
            return list_id if isinstance(list_id, str) else None

        if interactive_type == "nfm_reply":
            nfm_reply = interactive.get("nfm_reply", {})
            response_json = nfm_reply.get("response_json")
            if isinstance(response_json, str):
                return response_json
            if isinstance(response_json, dict):
                return json.dumps(response_json)

        return None

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "whatsapp", SimpleNamespace()), "webhook", None),
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
            "platform": "whatsapp",
            "channel_key": "whatsapp",
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

    def _resolve_default_phone_number_id(self) -> str | None:
        return self._coerce_nonempty_string(
            getattr(
                getattr(
                    getattr(self._config, "whatsapp", SimpleNamespace()),
                    "business",
                    SimpleNamespace(),
                ),
                "phone_number_id",
                None,
            )
        )

    def _extract_phone_number_id(self, event_value: dict[str, Any]) -> str | None:
        metadata = event_value.get("metadata")
        if isinstance(metadata, dict):
            configured = self._coerce_nonempty_string(metadata.get("phone_number_id"))
            if configured is not None:
                return configured
        return self._resolve_default_phone_number_id()

    async def _resolve_ingress_route(
        self,
        *,
        phone_number_id: str | None,
        webhook_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        claims = (
            {"phone_number_id": phone_number_id}
            if phone_number_id is not None
            else {}
        )
        resolution = await self._ingress_router().resolve(
            IngressRouteRequest(
                platform="whatsapp",
                channel_key="whatsapp",
                identifier_type="phone_number_id",
                identifier_value=phone_number_id,
                claims=claims,
            )
        )
        try:
            ingress_route = resolve_ingress_route_context(
                platform="whatsapp",
                channel_key="whatsapp",
                routing=resolution,
                source="whatsapp.ingress_routing",
                identifier_claims=claims,
            )
        except ContextScopeResolutionError as exc:
            self._increment_metric("whatsapp.ipc.route.unresolved")
            reason_code = str(exc.reason_code or "route_unresolved")
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=webhook_payload,
                reason_code="route_unresolved",
                error_message=str(exc),
            )
            self._logging_gateway.warning(
                "Dropped WhatsApp ingress due to unresolved route "
                f"reason_code={reason_code} phone_number_id={phone_number_id!r}."
            )
            return None

        if resolution.ok is not True:
            self._increment_metric("whatsapp.ipc.route.fallback_global")
            self._logging_gateway.warning(
                "Using global tenant fallback for WhatsApp ingress "
                f"(reason_code={resolution.reason_code} phone_number_id={phone_number_id!r})."
            )
        return ingress_route

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
            self._increment_metric("whatsapp.ipc.dead_letter.write_success")
        except SQLAlchemyError as exc:
            self._increment_metric("whatsapp.ipc.dead_letter.write_failure")
            self._logging_gateway.error(
                "Failed to write WhatsApp dead-letter event."
                f" reason_code={reason_code}"
                f" error={type(exc).__name__}: {exc}"
            )

    async def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        event_id = event_payload.get("id") if isinstance(event_payload.get("id"), str) else None
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
            self._increment_metric("whatsapp.ipc.dedupe.miss")
            return False
        except IntegrityError:
            self._increment_metric("whatsapp.ipc.dedupe.hit")
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
            self._increment_metric("whatsapp.ipc.dedupe.error")
            self._logging_gateway.error(
                "WhatsApp dedupe lookup failed."
                f" error={type(exc).__name__}: {exc}"
            )
            return False

    @staticmethod
    def _get_contact_for_sender(contacts: list, sender: str | None) -> dict | None:
        if not isinstance(contacts, list):
            return None

        for contact in contacts:
            if (
                isinstance(contact, dict)
                and isinstance(sender, str)
                and contact.get("wa_id") == sender
            ):
                return contact

        for contact in contacts:
            if isinstance(contact, dict):
                return contact

        return None

    async def _emit_processing_signal(
        self,
        *,
        sender: str,
        message_id: str | None,
        state: str,
    ) -> None:
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
                    "WhatsApp thinking signal reported failure "
                    f"(sender={sender} state={normalized_state})."
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "WhatsApp thinking signal raised unexpectedly "
                f"(sender={sender} state={state}): {exc}"
            )

    async def _process_message_event(
        self,
        event_value: dict,
        message: dict,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        if ingress_route is None:
            ingress_route = self._normalize_ingress_route(
                getattr(self, "_active_ingress_route", None)
            )
        else:
            ingress_route = self._normalize_ingress_route(ingress_route)
        started = time.perf_counter()
        correlation_id = message.get("id")
        self._logging_gateway.debug(
            f"[cid={correlation_id}] Process WhatsApp message event "
            f"type={message.get('type')}."
        )
        sender = message.get("from")
        contact = self._get_contact_for_sender(event_value.get("contacts"), sender)

        if not isinstance(sender, str) or sender == "":
            candidate_sender = (
                contact.get("wa_id") if isinstance(contact, dict) else None
            )
            sender = candidate_sender if isinstance(candidate_sender, str) else None

        if not isinstance(sender, str) or sender == "":
            self._logging_gateway.error("Malformed WhatsApp message payload.")
            return

        if await self._is_duplicate_event("message", message):
            self._logging_gateway.debug("Skip duplicate WhatsApp message event.")
            return

        if self._config.mugen.beta.active:
            beta_users: list = self._config.whatsapp.beta.users
            if sender not in beta_users:
                await self._client.send_text_message(
                    message=self._config.mugen.beta.message,
                    recipient=sender,
                )
                return

        known_users = await self._user_service.get_known_users_list()
        known_users = known_users if isinstance(known_users, dict) else {}
        if sender not in known_users.keys():
            profile_name = sender
            if isinstance(contact, dict):
                contact_profile = contact.get("profile")
                if isinstance(contact_profile, dict):
                    contact_name = contact_profile.get("name")
                    if isinstance(contact_name, str) and contact_name != "":
                        profile_name = contact_name
            self._logging_gateway.debug(f"New WhatsApp contact: {sender}")
            await self._user_service.add_known_user(
                sender,
                profile_name,
                sender,
            )

        message_id = message["id"] if isinstance(message.get("id"), str) else None
        await self._emit_processing_signal(
            sender=sender,
            message_id=message_id,
            state=PROCESSING_STATE_START,
        )
        try:
            message_responses: list[dict] | None = []
            try:
                match message["type"]:
                    case "audio":
                        get_media_url = await self._client.retrieve_media_url(
                            message["audio"]["id"],
                        )
                        media_url = self._extract_api_data(
                            get_media_url, "audio media URL"
                        )
                        if media_url and "url" in media_url.keys():
                            get_media = await self._client.download_media(
                                media_url["url"],
                                message["audio"]["mime_type"],
                            )

                            if get_media is not None:
                                message_responses = (
                                    await self._messaging_service.handle_audio_message(
                                        "whatsapp",
                                        room_id=sender,
                                        sender=sender,
                                        message=self._merge_ingress_metadata(
                                            payload={
                                                "message": message,
                                                "file": get_media,
                                            },
                                            ingress_route=ingress_route,
                                        ),
                                    )
                                )
                    case "document":
                        get_media_url = await self._client.retrieve_media_url(
                            message["document"]["id"],
                        )
                        media_url = self._extract_api_data(
                            get_media_url, "document media URL"
                        )
                        if media_url and "url" in media_url.keys():
                            get_media = await self._client.download_media(
                                media_url["url"],
                                message["document"]["mime_type"],
                            )

                            if get_media is not None:
                                message_responses = (
                                    await self._messaging_service.handle_file_message(
                                        "whatsapp",
                                        room_id=sender,
                                        sender=sender,
                                        message=self._merge_ingress_metadata(
                                            payload={
                                                "message": message,
                                                "file": get_media,
                                            },
                                            ingress_route=ingress_route,
                                        ),
                                    )
                                )
                    case "image":
                        get_media_url = await self._client.retrieve_media_url(
                            message["image"]["id"],
                        )
                        media_url = self._extract_api_data(
                            get_media_url, "image media URL"
                        )
                        if media_url and "url" in media_url.keys():
                            get_media = await self._client.download_media(
                                media_url["url"],
                                message["image"]["mime_type"],
                            )

                            if get_media is not None:
                                message_responses = (
                                    await self._messaging_service.handle_image_message(
                                        "whatsapp",
                                        room_id=sender,
                                        sender=sender,
                                        message=self._merge_ingress_metadata(
                                            payload={
                                                "message": message,
                                                "file": get_media,
                                            },
                                            ingress_route=ingress_route,
                                        ),
                                    )
                                )
                    case "text" | "interactive" | "button":
                        text_message = self._extract_user_text(message)
                        if text_message is None:
                            await self._call_message_handlers(
                                message=message,
                                message_type=message["type"],
                                sender=sender,
                            )
                        else:
                            message_responses = (
                                await self._messaging_service.handle_text_message(
                                    "whatsapp",
                                    room_id=sender,
                                    sender=sender,
                                    message=text_message,
                                    message_context=self._compose_message_context(
                                        ingress_route=ingress_route,
                                    ),
                                )
                            )
                    case "video":
                        get_media_url = await self._client.retrieve_media_url(
                            message["video"]["id"],
                        )
                        media_url = self._extract_api_data(
                            get_media_url, "video media URL"
                        )
                        if media_url and "url" in media_url.keys():
                            get_media = await self._client.download_media(
                                media_url["url"],
                                message["video"]["mime_type"],
                            )

                            if get_media is not None:
                                message_responses = (
                                    await self._messaging_service.handle_video_message(
                                        "whatsapp",
                                        room_id=sender,
                                        sender=sender,
                                        message=self._merge_ingress_metadata(
                                            payload={
                                                "message": message,
                                                "file": get_media,
                                            },
                                            ingress_route=ingress_route,
                                        ),
                                    )
                                )
                    case _:
                        await self._call_message_handlers(
                            message=message,
                            message_type=message["type"],
                            sender=sender,
                        )
            except (KeyError, TypeError):
                self._logging_gateway.error("Malformed WhatsApp message payload.")
                return

            self._logging_gateway.debug("Send responses to user.")
            for response in message_responses or []:
                await self._send_response_to_user(response=response, sender=sender)
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"[cid={correlation_id}] WhatsApp message event completed "
                f"latency_ms={latency_ms:.2f}."
            )
        finally:
            await self._emit_processing_signal(
                sender=sender,
                message_id=message_id,
                state=PROCESSING_STATE_STOP,
            )

    async def _process_status_event(
        self,
        status: dict,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        if ingress_route is None:
            ingress_route = self._normalize_ingress_route(
                getattr(self, "_active_ingress_route", None)
            )
        else:
            ingress_route = self._normalize_ingress_route(ingress_route)
        started = time.perf_counter()
        correlation_id = status.get("id")
        self._logging_gateway.debug(
            f"[cid={correlation_id}] Process WhatsApp status event "
            f"status={status.get('status')}."
        )
        if await self._is_duplicate_event("status", status):
            self._logging_gateway.debug("Skip duplicate WhatsApp status event.")
            return

        await self._call_message_handlers(
            message=status,
            message_type="status",
        )
        latency_ms = (time.perf_counter() - started) * 1000
        self._logging_gateway.debug(
            f"[cid={correlation_id}] WhatsApp status event completed "
            f"latency_ms={latency_ms:.2f}."
        )

    async def _upload_response_media(self, response: dict, context: str) -> dict | None:
        file_data = response.get("file")
        if not isinstance(file_data, dict):
            self._logging_gateway.error(f"Missing file payload for {context} response.")
            return None

        uri = file_data.get("uri")
        content_type = file_data.get("type")
        if not isinstance(uri, str) or not isinstance(content_type, str):
            self._logging_gateway.error(f"Invalid file payload for {context} response.")
            return None

        upload_response = await self._client.upload_media(uri, content_type)
        upload_data = self._extract_api_data(upload_response, f"{context} upload")
        if upload_data is None:
            return None

        media_id = upload_data.get("id")
        if not isinstance(media_id, str) or media_id == "":
            self._logging_gateway.error(f"{context} upload did not return media id.")
            return None

        return {
            "id": media_id,
            "file": file_data,
        }

    async def _send_response_to_user(self, response: dict, sender: str) -> None:
        response_type = response.get("type")
        reply_to = response.get("reply_to")
        if not isinstance(reply_to, str):
            reply_to = None

        if response_type == "audio":
            uploaded = await self._upload_response_media(response, "audio")
            if uploaded is None:
                return
            send_result = await self._client.send_audio_message(
                audio={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "audio send")
            return

        if response_type == "file":
            uploaded = await self._upload_response_media(response, "document")
            if uploaded is None:
                return
            document = {
                "id": uploaded["id"],
            }
            file_name = uploaded["file"].get("name")
            if isinstance(file_name, str) and file_name != "":
                document["filename"] = file_name
            send_result = await self._client.send_document_message(
                document=document,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "document send")
            return

        if response_type == "image":
            uploaded = await self._upload_response_media(response, "image")
            if uploaded is None:
                return
            send_result = await self._client.send_image_message(
                image={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "image send")
            return

        if response_type == "video":
            uploaded = await self._upload_response_media(response, "video")
            if uploaded is None:
                return
            send_result = await self._client.send_video_message(
                video={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "video send")
            return

        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str):
                self._logging_gateway.error("Missing text content in response payload.")
                return
            send_result = await self._client.send_text_message(
                message=content,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "text send")
            return

        if response_type == "contacts":
            contacts = response.get("contacts", response.get("content"))
            send_result = await self._client.send_contacts_message(
                contacts=contacts,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "contacts send")
            return

        if response_type == "location":
            location = response.get("location", response.get("content"))
            if not isinstance(location, dict):
                self._logging_gateway.error("Missing location payload in response.")
                return
            send_result = await self._client.send_location_message(
                location=location,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "location send")
            return

        if response_type == "interactive":
            interactive = response.get("interactive", response.get("content"))
            if not isinstance(interactive, dict):
                self._logging_gateway.error("Missing interactive payload in response.")
                return
            send_result = await self._client.send_interactive_message(
                interactive=interactive,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "interactive send")
            return

        if response_type == "template":
            template = response.get("template", response.get("content"))
            if not isinstance(template, dict):
                self._logging_gateway.error("Missing template payload in response.")
                return
            send_result = await self._client.send_template_message(
                template=template,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "template send")
            return

        if response_type == "sticker":
            sticker = response.get("sticker", response.get("content"))
            if not isinstance(sticker, dict):
                self._logging_gateway.error("Missing sticker payload in response.")
                return
            send_result = await self._client.send_sticker_message(
                sticker=sticker,
                recipient=sender,
                reply_to=reply_to,
            )
            self._extract_api_data(send_result, "sticker send")
            return

        if response_type == "reaction":
            reaction = response.get("reaction", response.get("content"))
            if not isinstance(reaction, dict):
                self._logging_gateway.error("Missing reaction payload in response.")
                return
            send_result = await self._client.send_reaction_message(
                reaction=reaction,
                recipient=sender,
            )
            self._extract_api_data(send_result, "reaction send")
            return

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        self._logging_gateway.debug(
            "WhatsAppWACAPIIPCExtension: Executing command:"
            f" {request.command}"
        )
        match request.command:
            case "whatsapp_wacapi_event":
                await self._wacapi_event(request)
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

    async def _wacapi_event(self, request: IPCCommandRequest) -> None:
        """Process WhatsApp Cloud API event."""
        started = time.perf_counter()
        event_payload = request.data if isinstance(request.data, dict) else {}
        try:
            event = request.data
            if not isinstance(event, dict):
                raise TypeError
            self._active_ingress_route = None
            entries = event["entry"]
            if not isinstance(entries, list):
                raise TypeError

            found_event_payload = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                changes = entry.get("changes")
                if not isinstance(changes, list):
                    continue

                for change in changes:
                    if not isinstance(change, dict):
                        continue

                    event_value = change.get("value")
                    if not isinstance(event_value, dict):
                        continue

                    found_event_payload = True
                    phone_number_id = self._extract_phone_number_id(event_value)
                    ingress_route = await self._resolve_ingress_route(
                        phone_number_id=phone_number_id,
                        webhook_payload=event_value,
                    )
                    if ingress_route is None:
                        continue
                    self._active_ingress_route = ingress_route

                    messages = event_value.get("messages")
                    if isinstance(messages, list):
                        for message in messages:
                            if not isinstance(message, dict):
                                self._logging_gateway.error(
                                    "Malformed WhatsApp message payload."
                                )
                                continue
                            await self._process_message_event(event_value, message)

                    statuses = event_value.get("statuses")
                    if isinstance(statuses, list):
                        for status in statuses:
                            if not isinstance(status, dict):
                                self._logging_gateway.error(
                                    "Malformed WhatsApp status payload."
                                )
                                continue
                            await self._process_status_event(status)
                    self._active_ingress_route = None

            if not found_event_payload:
                raise TypeError
        except (KeyError, TypeError):
            self._increment_metric("whatsapp.ipc.event.malformed")
            self._logging_gateway.error("Malformed WhatsApp event payload.")
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=event_payload,
                reason_code="malformed_payload",
                error_message="Malformed WhatsApp event payload.",
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._increment_metric("whatsapp.ipc.event.processed_failed")
            self._logging_gateway.error(
                "Unhandled WhatsApp event processing failure."
                f" error={type(exc).__name__}: {exc}"
            )
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=event_payload,
                reason_code="processing_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            )
        else:
            self._increment_metric("whatsapp.ipc.event.processed_ok")
        finally:
            latency_ms = (time.perf_counter() - started) * 1000
            self._logging_gateway.debug(
                f"WhatsApp webhook event processing latency_ms={latency_ms:.2f}."
            )

    async def _call_message_handlers(
        self,
        message: dict,
        message_type: str,
        sender: str = None,
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
        if ingress_route is None:
            active_route = getattr(self, "_active_ingress_route", None)
            if isinstance(active_route, dict):
                ingress_route = dict(active_route)
        resolved = context_scope_from_ingress_route(
            platform="whatsapp",
            channel_key="whatsapp",
            room_id=sender or "",
            sender_id=sender or "",
            ingress_route=ingress_route,
            source="whatsapp.ipc_extension",
        )
        hits: int = 0
        message_handlers: list[IMHExtension] = self._messaging_service.mh_extensions
        for handler in message_handlers:
            if (
                handler.platform_supported("whatsapp")
            ) and message_type in handler.message_types:
                await asyncio.gather(
                    asyncio.create_task(
                        handler.handle_message(
                            platform="whatsapp",
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
                    )
                )
                hits += 1
        if hits == 0:
            self._logging_gateway.debug(f"Unsupported message type: {message_type}.")
            if sender:
                await self._client.send_text_message(
                    message="Unsupported message type..",
                    recipient=sender,
                    reply_to=message["id"],
                )
