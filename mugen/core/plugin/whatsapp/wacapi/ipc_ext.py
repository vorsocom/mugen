"""Provides an implementation of IIPCExtension for WhatsApp Cloud API support."""

__all__ = ["WhatsAppWACAPIIPCExtension"]

import asyncio
import hashlib
import inspect
import json
import time
import uuid
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
from mugen.core.utility.client_profile_runtime import (
    client_profile_id_from_ingress_route,
    client_profile_scope,
    normalize_client_profile_id,
)
from mugen.core.utility.messaging_client_user_access import (
    MessagingClientUserAccessPolicy,
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class WhatsAppWACAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for WhatsApp Cloud API support."""

    _event_dedup_table = "whatsapp_wacapi_event_dedup"
    _event_dead_letter_table = "whatsapp_wacapi_event_dead_letter"
    _default_event_dedup_ttl_seconds = 86400
    _delivery_correlation_id_max_bytes = 256
    _delivery_response_types = frozenset(
        {
            "audio",
            "contacts",
            "file",
            "image",
            "interactive",
            "location",
            "reaction",
            "sticker",
            "template",
            "text",
            "video",
        }
    )

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
            "whatsapp_ingress_event",
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

        if payload.get("delivery_outcome") == "ambiguous":
            self._logging_gateway.warning(
                f"{context} has an ambiguous provider delivery outcome."
            )
            return None

        if payload.get("ok") is not True:
            self._logging_gateway.error(f"{context} failed.")
            error = payload.get("error")
            if error not in [None, ""]:
                self._logging_gateway.error(str(error))
            return None

        data = payload.get("data")
        if data is None:
            return {}

        if not isinstance(data, dict):
            self._logging_gateway.error(f"Unexpected payload type for {context}.")
            return None

        return data

    def _delivery_correlation_id(self, response: dict) -> str | None:
        if "delivery_context" not in response:
            return None
        delivery_context = response.get("delivery_context")
        if not isinstance(delivery_context, dict) or set(delivery_context) != {
            "correlation_id"
        }:
            self._logging_gateway.warning(
                "Ignore invalid WhatsApp delivery_context payload."
            )
            return None
        correlation_id = delivery_context.get("correlation_id")
        if not isinstance(correlation_id, str) or correlation_id.strip() == "":
            self._logging_gateway.warning(
                "Ignore invalid WhatsApp delivery correlation id."
            )
            return None
        try:
            correlation_size = len(correlation_id.encode("utf-8"))
        except UnicodeEncodeError:
            correlation_size = self._delivery_correlation_id_max_bytes + 1
        if correlation_size > self._delivery_correlation_id_max_bytes:
            self._logging_gateway.warning(
                "Ignore oversized WhatsApp delivery correlation id."
            )
            return None
        return correlation_id

    @staticmethod
    def _safe_http_status(value: object) -> int | None:
        if type(value) is not int or value < 100 or value > 599:
            return None
        return value

    @staticmethod
    def _safe_classification_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        try:
            encoded_size = len(normalized.encode("utf-8"))
        except UnicodeEncodeError:
            return None
        if normalized == "" or encoded_size > 128 or not normalized.isprintable():
            return None
        return normalized

    def _error_classification(
        self,
        result: object,
        *,
        default_type: str,
    ) -> dict[str, object]:
        classification: dict[str, object] = {"type": default_type}
        if not isinstance(result, dict):
            return classification
        data = result.get("data")
        if not isinstance(data, dict):
            return classification
        error = data.get("error")
        if not isinstance(error, dict):
            return classification
        provider_type = self._safe_classification_text(error.get("type"))
        if provider_type is not None:
            classification["type"] = provider_type
        code = error.get("code")
        if type(code) is int:
            classification["code"] = code
        subcode = error.get("error_subcode", error.get("subcode"))
        if type(subcode) is int:
            classification["subcode"] = subcode
        return classification

    @staticmethod
    def _base_delivery_receipt(
        *,
        response_type: str,
        correlation_id: str,
        occurred_at: str,
        outcome: str,
    ) -> dict[str, object]:
        return {
            "platform": "whatsapp",
            "channel": "whatsapp",
            "response_type": response_type,
            "correlation_id": correlation_id,
            "outcome": outcome,
            "occurred_at": occurred_at,
        }

    def _failed_delivery_receipt(
        self,
        *,
        response_type: str,
        correlation_id: str,
        occurred_at: str,
        result: object,
        classification_type: str,
    ) -> dict[str, object]:
        receipt = self._base_delivery_receipt(
            response_type=response_type,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            outcome="failed",
        )
        receipt["error_classification"] = self._error_classification(
            result,
            default_type=classification_type,
        )
        if isinstance(result, dict):
            status = self._safe_http_status(result.get("status"))
            if status is not None:
                receipt["http_status"] = status
        return receipt

    def _delivery_receipt_from_result(
        self,
        *,
        response_type: str,
        correlation_id: str,
        occurred_at: str,
        result: object,
    ) -> dict[str, object]:
        if not isinstance(result, dict):
            return self._failed_delivery_receipt(
                response_type=response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                result=result,
                classification_type="invalid_provider_response",
            )
        if result.get("delivery_outcome") == "ambiguous":
            receipt = self._base_delivery_receipt(
                response_type=response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                outcome="ambiguous",
            )
            receipt["error_classification"] = self._error_classification(
                result,
                default_type="ambiguous_delivery",
            )
            status = self._safe_http_status(result.get("status"))
            if status is not None:
                receipt["http_status"] = status
            return receipt
        if "ok" in result and result.get("ok") is not True:
            return self._failed_delivery_receipt(
                response_type=response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                result=result,
                classification_type="provider_rejected",
            )
        if "status" in result:
            status = self._safe_http_status(result.get("status"))
            if status is None or status < 200 or status >= 300:
                return self._failed_delivery_receipt(
                    response_type=response_type,
                    correlation_id=correlation_id,
                    occurred_at=occurred_at,
                    result=result,
                    classification_type=(
                        "provider_http_error"
                        if status is not None
                        else "invalid_provider_response"
                    ),
                )
        data = result.get("data")
        messages = data.get("messages") if isinstance(data, dict) else None
        first_message = messages[0] if isinstance(messages, list) and messages else None
        provider_message_id = (
            first_message.get("id") if isinstance(first_message, dict) else None
        )
        if (
            not isinstance(provider_message_id, str)
            or provider_message_id.strip() == ""
        ):
            return self._failed_delivery_receipt(
                response_type=response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                result=result,
                classification_type="invalid_provider_response",
            )
        receipt = self._base_delivery_receipt(
            response_type=response_type,
            correlation_id=correlation_id,
            occurred_at=occurred_at,
            outcome="accepted",
        )
        receipt["provider_message_id"] = provider_message_id.strip()
        return receipt

    async def _emit_delivery_receipt(
        self,
        response: dict,
        receipt: dict[str, object],
    ) -> None:
        emitter = getattr(response, "emit_delivery_receipt", None)
        if not callable(emitter):
            self._logging_gateway.warning(
                "WhatsApp delivery receipt has no originating handler provenance."
            )
            return
        await emitter(receipt)

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

    @staticmethod
    def _extract_flow_reply_metadata(message: dict) -> dict[str, Any] | None:
        if message.get("type") != "interactive":
            return None
        interactive = message.get("interactive", {})
        if not isinstance(interactive, dict) or interactive.get("type") != "nfm_reply":
            return None
        nfm_reply = interactive.get("nfm_reply", {})
        if not isinstance(nfm_reply, dict):
            return None
        return {
            "type": "nfm_reply",
            "flow_token": nfm_reply.get("flow_token"),
            "flow_name": nfm_reply.get("flow_name"),
            "response_json": nfm_reply.get("response_json"),
        }

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        raw_value = getattr(
            getattr(
                getattr(self._config, "whatsapp", SimpleNamespace()), "webhook", None
            ),
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

    async def _resolve_user_access_policy(self) -> MessagingClientUserAccessPolicy:
        policy_provider = getattr(self._client, "user_access_policy", None)
        if not callable(policy_provider):
            return MessagingClientUserAccessPolicy()

        resolved = policy_provider()
        if inspect.isawaitable(resolved):
            resolved = await resolved
        if isinstance(resolved, MessagingClientUserAccessPolicy):
            return resolved
        if resolved is None:
            return MessagingClientUserAccessPolicy()
        raise RuntimeError(
            "WhatsApp client user_access_policy returned an invalid result."
        )

    async def _resolve_ingress_route(
        self,
        *,
        phone_number_id: str | None,
        webhook_payload: dict[str, Any],
        authenticated_client_profile_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        claims = (
            {"phone_number_id": phone_number_id} if phone_number_id is not None else {}
        )
        resolution = await self._ingress_router().resolve(
            IngressRouteRequest(
                platform="whatsapp",
                channel_key="whatsapp",
                identifier_type="phone_number_id",
                identifier_value=phone_number_id,
                claims=claims,
                authenticated_client_profile_id=authenticated_client_profile_id,
            )
        )
        try:
            ingress_route = resolve_ingress_route_context(
                platform="whatsapp",
                channel_key="whatsapp",
                routing=resolution,
                source="whatsapp.ingress_routing",
                identifier_claims=claims,
                global_fallback_reasons=(),
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
                f"reason_code={reason_code}."
            )
            return None
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
                f" error_type={type(exc).__name__}."
            )

    async def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        event_id = (
            event_payload.get("id")
            if isinstance(event_payload.get("id"), str)
            else None
        )
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
                "WhatsApp dedupe lookup failed." f" error_type={type(exc).__name__}."
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
                    f"state={normalized_state}."
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "WhatsApp thinking signal raised unexpectedly "
                f"state={state} error_type={type(exc).__name__}."
            )

    async def _process_message_event(
        self,
        event_value: dict,
        message: dict,
        ingress_route: dict[str, Any] | None = None,
        *,
        skip_dedupe: bool = False,
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

        if skip_dedupe is not True and await self._is_duplicate_event(
            "message", message
        ):
            self._logging_gateway.debug("Skip duplicate WhatsApp message event.")
            return

        try:
            user_access_policy = await self._resolve_user_access_policy()
        except RuntimeError as exc:
            self._logging_gateway.warning(
                "WhatsApp sender rejected. Reason: Invalid user access policy."
                " reason_code=invalid_user_access_policy"
                f" error_type={type(exc).__name__}."
            )
            return

        if not user_access_policy.allows(sender):
            denied_message = user_access_policy.denied_message
            if denied_message is not None:
                await self._client.send_text_message(
                    message=denied_message,
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
            self._logging_gateway.debug("New WhatsApp contact discovered.")
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
                            ingress_metadata = {
                                "ingress_route": dict(ingress_route),
                            }
                            flow_reply_metadata = self._extract_flow_reply_metadata(
                                message
                            )
                            if flow_reply_metadata is not None:
                                ingress_metadata["whatsapp_flow_reply"] = (
                                    flow_reply_metadata
                                )
                            message_responses = (
                                await self._messaging_service.handle_text_message(
                                    "whatsapp",
                                    room_id=sender,
                                    sender=sender,
                                    message=text_message,
                                    message_context=self._compose_message_context(
                                        ingress_route=ingress_route,
                                    ),
                                    ingress_metadata=ingress_metadata,
                                    message_id=message_id,
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
        *,
        skip_dedupe: bool = False,
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
        if skip_dedupe is not True and await self._is_duplicate_event("status", status):
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

    async def _dispatch_response_to_user(
        self,
        *,
        response: dict,
        response_type: object,
        sender: str,
        reply_to: str | None,
    ) -> tuple[object, str, str | None]:
        if response_type == "audio":
            uploaded = await self._upload_response_media(response, "audio")
            if uploaded is None:
                return None, "audio send", "media_upload_failed"
            send_result = await self._client.send_audio_message(
                audio={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "audio send", None

        if response_type == "file":
            uploaded = await self._upload_response_media(response, "document")
            if uploaded is None:
                return None, "document send", "media_upload_failed"
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
            return send_result, "document send", None

        if response_type == "image":
            uploaded = await self._upload_response_media(response, "image")
            if uploaded is None:
                return None, "image send", "media_upload_failed"
            send_result = await self._client.send_image_message(
                image={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "image send", None

        if response_type == "video":
            uploaded = await self._upload_response_media(response, "video")
            if uploaded is None:
                return None, "video send", "media_upload_failed"
            send_result = await self._client.send_video_message(
                video={"id": uploaded["id"]},
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "video send", None

        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str):
                self._logging_gateway.error("Missing text content in response payload.")
                return None, "text send", "invalid_response"
            send_result = await self._client.send_text_message(
                message=content,
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "text send", None

        if response_type == "contacts":
            contacts = response.get("contacts", response.get("content"))
            send_result = await self._client.send_contacts_message(
                contacts=contacts,
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "contacts send", None

        if response_type == "location":
            location = response.get("location", response.get("content"))
            if not isinstance(location, dict):
                self._logging_gateway.error("Missing location payload in response.")
                return None, "location send", "invalid_response"
            send_result = await self._client.send_location_message(
                location=location,
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "location send", None

        if response_type == "interactive":
            interactive = response.get("interactive", response.get("content"))
            if not isinstance(interactive, dict):
                self._logging_gateway.error("Missing interactive payload in response.")
                return None, "interactive send", "invalid_response"
            send_result = await self._client.send_interactive_message(
                interactive=interactive,
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "interactive send", None

        if response_type == "template":
            template = response.get("template", response.get("content"))
            if not isinstance(template, dict):
                self._logging_gateway.error("Missing template payload in response.")
                return None, "template send", "invalid_response"
            send_result = await self._client.send_template_message(
                template=template,
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "template send", None

        if response_type == "sticker":
            sticker = response.get("sticker", response.get("content"))
            if not isinstance(sticker, dict):
                self._logging_gateway.error("Missing sticker payload in response.")
                return None, "sticker send", "invalid_response"
            send_result = await self._client.send_sticker_message(
                sticker=sticker,
                recipient=sender,
                reply_to=reply_to,
            )
            return send_result, "sticker send", None

        if response_type == "reaction":
            reaction = response.get("reaction", response.get("content"))
            if not isinstance(reaction, dict):
                self._logging_gateway.error("Missing reaction payload in response.")
                return None, "reaction send", "invalid_response"
            send_result = await self._client.send_reaction_message(
                reaction=reaction,
                recipient=sender,
            )
            return send_result, "reaction send", None

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")
        return None, "response send", "invalid_response"

    async def _send_response_to_user(self, response: dict, sender: str) -> None:
        response_type = response.get("type")
        reply_to = response.get("reply_to")
        if not isinstance(reply_to, str):
            reply_to = None

        if response_type == "control":
            return

        safe_response_type = (
            response_type
            if isinstance(response_type, str)
            and response_type in self._delivery_response_types
            else "unknown"
        )
        correlation_id = self._delivery_correlation_id(response)
        occurred_at = _utc_now_iso()
        try:
            send_result, send_context, preparation_failure = (
                await self._dispatch_response_to_user(
                    response=response,
                    response_type=response_type,
                    sender=sender,
                    reply_to=reply_to,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if correlation_id is None:
                raise
            self._logging_gateway.error(
                "WhatsApp response delivery raised a client exception "
                f"(response_type={safe_response_type} "
                f"error_type={type(exc).__name__})."
            )
            receipt = self._failed_delivery_receipt(
                response_type=safe_response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                result=None,
                classification_type=type(exc).__name__,
            )
            await self._emit_delivery_receipt(response, receipt)
            return

        if correlation_id is None:
            if preparation_failure is None:
                self._extract_api_data(send_result, send_context)
            return

        if preparation_failure is not None:
            receipt = self._failed_delivery_receipt(
                response_type=safe_response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                result=None,
                classification_type=preparation_failure,
            )
        else:
            receipt = self._delivery_receipt_from_result(
                response_type=safe_response_type,
                correlation_id=correlation_id,
                occurred_at=occurred_at,
                result=send_result,
            )
            if receipt["outcome"] != "accepted":
                self._extract_api_data(send_result, send_context)
            if receipt["outcome"] == "failed":
                self._logging_gateway.error(
                    f"{send_context} did not return an accepted provider message."
                )
        await self._emit_delivery_receipt(response, receipt)

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        handler_name = type(self).__name__
        self._logging_gateway.debug(
            "WhatsAppWACAPIIPCExtension: Executing command:" f" {request.command}"
        )
        match request.command:
            case "whatsapp_ingress_event":
                await self._whatsapp_ingress_event(request)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
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

    async def _whatsapp_ingress_event(self, request: IPCCommandRequest) -> None:
        payload = request.data if isinstance(request.data, dict) else {}
        event_payload = payload.get("payload")
        if not isinstance(event_payload, dict):
            raise TypeError("WhatsApp ingress payload.event must be a dict.")

        provider_context = payload.get("provider_context")
        provider_context = (
            provider_context if isinstance(provider_context, dict) else {}
        )
        client_profile_id = normalize_client_profile_id(
            payload.get("client_profile_id")
            or provider_context.get("client_profile_id")
        )
        if client_profile_id is None:
            raise ContextScopeResolutionError(
                reason_code="client_profile_mismatch",
                detail="whatsapp delivery requires its receiving client profile.",
            )
        ingress_route = self._normalize_ingress_route(
            provider_context.get("ingress_route")
        )
        phone_number_id = self._coerce_nonempty_string(
            provider_context.get("phone_number_id")
        )
        if (
            ingress_route.get("client_profile_id") in [None, ""]
            and phone_number_id is not None
        ):
            resolve_payload = (
                event_payload.get("event_value")
                if isinstance(event_payload.get("event_value"), dict)
                else event_payload
            )
            resolved = await self._resolve_ingress_route(
                phone_number_id=phone_number_id,
                webhook_payload=resolve_payload,
                authenticated_client_profile_id=client_profile_id,
            )
            if resolved is None:
                raise ContextScopeResolutionError(
                    reason_code="route_unresolved",
                    detail="whatsapp delivery could not resolve its route.",
                )
            ingress_route = resolved

        if client_profile_id_from_ingress_route(ingress_route) != client_profile_id:
            raise ContextScopeResolutionError(
                reason_code="client_profile_mismatch",
                detail="whatsapp route does not belong to its receiving client.",
            )
        with client_profile_scope(client_profile_id):
            message = event_payload.get("message")
            if isinstance(message, dict):
                event_value = (
                    event_payload.get("event_value")
                    if isinstance(event_payload.get("event_value"), dict)
                    else {}
                )
                await self._process_message_event(
                    event_value,
                    message,
                    ingress_route,
                    skip_dedupe=True,
                )
                return

            status = event_payload.get("status")
            if isinstance(status, dict):
                await self._process_status_event(
                    status,
                    ingress_route,
                    skip_dedupe=True,
                )

    async def _wacapi_event(self, request: IPCCommandRequest) -> None:
        """Process WhatsApp Cloud API event."""
        started = time.perf_counter()
        event_payload = request.data if isinstance(request.data, dict) else {}
        try:
            event = request.data
            if not isinstance(event, dict):
                raise TypeError
            if isinstance(event.get("payload"), dict):
                event = event.get("payload")
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
                    change_field = change.get("field")
                    if change_field is not None and change_field != "messages":
                        found_event_payload = True
                        continue

                    event_value = change.get("value")
                    if not isinstance(event_value, dict):
                        continue

                    found_event_payload = True
                    phone_number_id = self._extract_phone_number_id(event_value)
                    ingress_route = await self._resolve_ingress_route(
                        phone_number_id=phone_number_id,
                        webhook_payload=event_value,
                        authenticated_client_profile_id=normalize_client_profile_id(
                            event_payload.get("authenticated_client_profile_id")
                        ),
                    )
                    if ingress_route is None:
                        raise ContextScopeResolutionError(
                            reason_code="route_unresolved",
                            detail="WhatsApp delivery could not resolve its route.",
                        )
                    self._active_ingress_route = ingress_route
                    route_client_profile_id = client_profile_id_from_ingress_route(
                        ingress_route
                    )
                    if route_client_profile_id is None:
                        raise ContextScopeResolutionError(
                            reason_code="route_unresolved",
                            detail="WhatsApp delivery could not resolve its client.",
                        )
                    with client_profile_scope(route_client_profile_id):
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
        except ContextScopeResolutionError:
            self._increment_metric("whatsapp.ipc.event.processed_failed")
            raise
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
                f" error_type={type(exc).__name__}."
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
