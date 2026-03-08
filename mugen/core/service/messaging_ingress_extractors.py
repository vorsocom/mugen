"""Platform-specific helpers that normalize transport payloads into ingress events."""

from __future__ import annotations

__all__ = [
    "extract_line_stage_entries",
    "extract_signal_stage_entries",
    "extract_telegram_stage_entries",
    "extract_wechat_stage_entries",
    "extract_whatsapp_stage_entries",
]

import hashlib
import json
from types import SimpleNamespace
from typing import Any

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.service.ingress import (
    MessagingIngressEvent,
    MessagingIngressStageEntry,
)
from mugen.core.contract.service.ingress_routing import IngressRouteRequest
from mugen.core.service.context_scope_resolution import (
    ContextScopeResolutionError,
    resolve_ingress_route_context,
)
from mugen.core.service.ingress_routing import DefaultIngressRoutingService
from mugen.core.utility.platform_runtime_profile import (
    DEFAULT_RUNTIME_PROFILE_KEY,
    get_platform_profile_section,
)


def _nonempty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized if normalized != "" else None


def _json_hash(payload: object) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dedupe_key(event_type: str, event_id: str | None, payload: object) -> str:
    if isinstance(event_id, str) and event_id.strip() != "":
        return f"{event_type}:{event_id.strip()}"
    return f"{event_type}:{_json_hash(payload)}"


async def _resolve_ingress_route(
    *,
    platform: str,
    channel_key: str,
    identifier_type: str,
    identifier_value: str | None,
    claims: dict[str, str],
    relational_storage_gateway: IRelationalStorageGateway,
    logging_gateway: ILoggingGateway,
) -> dict[str, Any] | None:
    if identifier_value is None:
        return None
    router = DefaultIngressRoutingService(
        relational_storage_gateway=relational_storage_gateway,
        logging_gateway=logging_gateway,
    )
    resolution = await router.resolve(
        IngressRouteRequest(
            platform=platform,
            channel_key=channel_key,
            identifier_type=identifier_type,
            identifier_value=identifier_value,
            claims=claims,
        )
    )
    try:
        return resolve_ingress_route_context(
            platform=platform,
            channel_key=channel_key,
            routing=resolution,
            source=f"{platform}.ingress_routing",
            identifier_claims=claims,
            global_fallback_reasons=(),
        )
    except ContextScopeResolutionError as exc:
        logging_gateway.warning(
            "Shared ingress route resolution failed "
            f"(platform={platform} reason_code={exc.reason_code} "
            f"identifier_type={identifier_type} identifier_value={identifier_value!r})."
        )
        return None


def _runtime_profile_key_from_route(route: dict[str, Any] | None) -> str:
    if isinstance(route, dict):
        runtime_profile_key = _nonempty_text(route.get("runtime_profile_key"))
        if runtime_profile_key is not None:
            return runtime_profile_key
    return DEFAULT_RUNTIME_PROFILE_KEY


async def extract_line_stage_entries(
    *,
    path_token: str,
    payload: dict[str, Any],
    relational_storage_gateway: IRelationalStorageGateway,
    logging_gateway: ILoggingGateway,
) -> list[MessagingIngressStageEntry]:
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    ingress_route = await _resolve_ingress_route(
        platform="line",
        channel_key="line",
        identifier_type="path_token",
        identifier_value=path_token,
        claims={"path_token": path_token},
        relational_storage_gateway=relational_storage_gateway,
        logging_gateway=logging_gateway,
    )
    runtime_profile_key = _runtime_profile_key_from_route(ingress_route)
    entries: list[MessagingIngressStageEntry] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = _nonempty_text(event.get("type")) or "event"
        message = event.get("message")
        event_id = _nonempty_text(event.get("webhookEventId"))
        if event_id is None and isinstance(message, dict):
            event_id = _nonempty_text(message.get("id"))
        source = event.get("source")
        sender = _nonempty_text(source.get("userId")) if isinstance(source, dict) else None
        entries.append(
            MessagingIngressStageEntry(
                ipc_command="line_ingress_event",
                event=MessagingIngressEvent(
                    version=1,
                    platform="line",
                    runtime_profile_key=runtime_profile_key,
                    source_mode="webhook",
                    event_type=event_type,
                    event_id=event_id,
                    dedupe_key=_dedupe_key(event_type, event_id, event),
                    identifier_type="path_token",
                    identifier_value=path_token,
                    room_id=sender,
                    sender=sender,
                    payload=event,
                    provider_context={
                        "ingress_route": ingress_route or {},
                        "path_token": path_token,
                    },
                ),
            )
        )
    return entries


async def extract_telegram_stage_entries(
    *,
    path_token: str,
    payload: dict[str, Any],
    relational_storage_gateway: IRelationalStorageGateway,
    logging_gateway: ILoggingGateway,
) -> list[MessagingIngressStageEntry]:
    ingress_route = await _resolve_ingress_route(
        platform="telegram",
        channel_key="telegram",
        identifier_type="path_token",
        identifier_value=path_token,
        claims={"path_token": path_token},
        relational_storage_gateway=relational_storage_gateway,
        logging_gateway=logging_gateway,
    )
    runtime_profile_key = _runtime_profile_key_from_route(ingress_route)
    update_id = payload.get("update_id")
    update_id_text = str(update_id) if update_id is not None else None
    entries: list[MessagingIngressStageEntry] = []

    message = payload.get("message")
    if isinstance(message, dict):
        chat = message.get("chat")
        room_id = str(chat.get("id")) if isinstance(chat, dict) and chat.get("id") is not None else None
        sender = None
        if isinstance(message.get("from"), dict):
            sender_value = message["from"].get("id")
            sender = str(sender_value) if sender_value is not None else None
        entries.append(
            MessagingIngressStageEntry(
                ipc_command="telegram_ingress_event",
                event=MessagingIngressEvent(
                    version=1,
                    platform="telegram",
                    runtime_profile_key=runtime_profile_key,
                    source_mode="webhook",
                    event_type="message",
                    event_id=update_id_text,
                    dedupe_key=_dedupe_key("message", update_id_text, message),
                    identifier_type="path_token",
                    identifier_value=path_token,
                    room_id=room_id,
                    sender=sender,
                    payload={"update": payload, "message": message},
                    provider_context={
                        "ingress_route": ingress_route or {},
                        "path_token": path_token,
                    },
                ),
            )
        )

    callback_query = payload.get("callback_query")
    if isinstance(callback_query, dict):
        callback_message = callback_query.get("message")
        chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
        room_id = str(chat.get("id")) if isinstance(chat, dict) and chat.get("id") is not None else None
        sender = None
        if isinstance(callback_query.get("from"), dict):
            sender_value = callback_query["from"].get("id")
            sender = str(sender_value) if sender_value is not None else None
        callback_id = _nonempty_text(callback_query.get("id")) or update_id_text
        entries.append(
            MessagingIngressStageEntry(
                ipc_command="telegram_ingress_event",
                event=MessagingIngressEvent(
                    version=1,
                    platform="telegram",
                    runtime_profile_key=runtime_profile_key,
                    source_mode="webhook",
                    event_type="callback_query",
                    event_id=callback_id,
                    dedupe_key=_dedupe_key("callback_query", callback_id, callback_query),
                    identifier_type="path_token",
                    identifier_value=path_token,
                    room_id=room_id,
                    sender=sender,
                    payload={"update": payload, "callback_query": callback_query},
                    provider_context={
                        "ingress_route": ingress_route or {},
                        "path_token": path_token,
                    },
                ),
            )
        )

    return entries


async def extract_wechat_stage_entries(
    *,
    path_token: str,
    provider: str,
    payload: dict[str, Any],
    relational_storage_gateway: IRelationalStorageGateway,
    logging_gateway: ILoggingGateway,
) -> list[MessagingIngressStageEntry]:
    ingress_route = await _resolve_ingress_route(
        platform="wechat",
        channel_key="wechat",
        identifier_type="path_token",
        identifier_value=path_token,
        claims={"path_token": path_token},
        relational_storage_gateway=relational_storage_gateway,
        logging_gateway=logging_gateway,
    )
    runtime_profile_key = _runtime_profile_key_from_route(ingress_route)
    sender = _nonempty_text(payload.get("FromUserName"))
    event_id = _nonempty_text(payload.get("MsgId"))
    event_type = f"{provider}:event"
    return [
        MessagingIngressStageEntry(
            ipc_command="wechat_ingress_event",
            event=MessagingIngressEvent(
                version=1,
                platform="wechat",
                runtime_profile_key=runtime_profile_key,
                source_mode="webhook",
                event_type=event_type,
                event_id=event_id,
                dedupe_key=_dedupe_key(event_type, event_id, payload),
                identifier_type="path_token",
                identifier_value=path_token,
                room_id=sender,
                sender=sender,
                payload=dict(payload),
                provider_context={
                    "ingress_route": ingress_route or {},
                    "path_token": path_token,
                    "provider": provider,
                },
            ),
        )
    ]


async def extract_whatsapp_stage_entries(
    *,
    payload: dict[str, Any],
    relational_storage_gateway: IRelationalStorageGateway,
    logging_gateway: ILoggingGateway,
) -> list[MessagingIngressStageEntry]:
    entries: list[MessagingIngressStageEntry] = []
    entry_list = payload.get("entry")
    if not isinstance(entry_list, list):
        return entries
    for entry in entry_list:
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
            metadata = event_value.get("metadata")
            phone_number_id = None
            if isinstance(metadata, dict):
                phone_number_id = _nonempty_text(metadata.get("phone_number_id"))
            ingress_route = await _resolve_ingress_route(
                platform="whatsapp",
                channel_key="whatsapp",
                identifier_type="phone_number_id",
                identifier_value=phone_number_id,
                claims={"phone_number_id": phone_number_id} if phone_number_id else {},
                relational_storage_gateway=relational_storage_gateway,
                logging_gateway=logging_gateway,
            )
            runtime_profile_key = _runtime_profile_key_from_route(ingress_route)
            contacts = event_value.get("contacts")
            messages = event_value.get("messages")
            if isinstance(messages, list):
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    sender = _nonempty_text(message.get("from"))
                    if sender is None and isinstance(contacts, list):
                        for contact in contacts:
                            if not isinstance(contact, dict):
                                continue
                            candidate = _nonempty_text(contact.get("wa_id"))
                            if candidate is not None:
                                sender = candidate
                                break
                    message_id = _nonempty_text(message.get("id"))
                    entries.append(
                        MessagingIngressStageEntry(
                            ipc_command="whatsapp_ingress_event",
                            event=MessagingIngressEvent(
                                version=1,
                                platform="whatsapp",
                                runtime_profile_key=runtime_profile_key,
                                source_mode="webhook",
                                event_type="message",
                                event_id=message_id,
                                dedupe_key=_dedupe_key("message", message_id, message),
                                identifier_type="phone_number_id",
                                identifier_value=phone_number_id,
                                room_id=sender,
                                sender=sender,
                                payload={"event_value": event_value, "message": message},
                                provider_context={
                                    "ingress_route": ingress_route or {},
                                    "phone_number_id": phone_number_id,
                                },
                            ),
                        )
                    )
            statuses = event_value.get("statuses")
            if isinstance(statuses, list):
                for status in statuses:
                    if not isinstance(status, dict):
                        continue
                    status_id = _nonempty_text(status.get("id"))
                    recipient = _nonempty_text(status.get("recipient_id"))
                    entries.append(
                        MessagingIngressStageEntry(
                            ipc_command="whatsapp_ingress_event",
                            event=MessagingIngressEvent(
                                version=1,
                                platform="whatsapp",
                                runtime_profile_key=runtime_profile_key,
                                source_mode="webhook",
                                event_type="status",
                                event_id=status_id,
                                dedupe_key=_dedupe_key("status", status_id, status),
                                identifier_type="phone_number_id",
                                identifier_value=phone_number_id,
                                room_id=recipient,
                                sender=recipient,
                                payload={"event_value": event_value, "status": status},
                                provider_context={
                                    "ingress_route": ingress_route or {},
                                    "phone_number_id": phone_number_id,
                                },
                            ),
                        )
                    )
    return entries


def _signal_envelope(payload: dict[str, Any]) -> dict[str, Any] | None:
    params = payload.get("params")
    if not isinstance(params, dict):
        return None
    envelope = params.get("envelope")
    return envelope if isinstance(envelope, dict) else None


def _signal_sender(envelope: dict[str, Any]) -> str | None:
    for key in ("sourceNumber", "sourceUuid", "source"):
        sender = _nonempty_text(envelope.get(key))
        if sender is not None:
            return sender
    return None


def _signal_event_id(envelope: dict[str, Any]) -> str | None:
    timestamp = envelope.get("timestamp")
    if isinstance(timestamp, bool):
        return None
    if not isinstance(timestamp, (int, float)):
        return None
    source = _signal_sender(envelope)
    if source is not None:
        return f"{source}:{int(timestamp)}"
    return str(int(timestamp))


def _signal_event_type(envelope: dict[str, Any]) -> str:
    data_message = envelope.get("dataMessage")
    receipt_message = envelope.get("receiptMessage")
    typing_message = envelope.get("typingMessage")
    if isinstance(data_message, dict):
        if isinstance(data_message.get("reaction"), dict):
            return "reaction"
        return "message"
    if isinstance(receipt_message, dict):
        return "receipt"
    if isinstance(typing_message, dict):
        return "typing"
    return "event"


def extract_signal_stage_entries(
    *,
    config: SimpleNamespace,
    payload: dict[str, Any],
) -> list[MessagingIngressStageEntry]:
    envelope = _signal_envelope(payload)
    if envelope is None:
        return []
    runtime_profile_key = _nonempty_text(payload.get("runtime_profile_key")) or DEFAULT_RUNTIME_PROFILE_KEY
    signal_cfg = get_platform_profile_section(
        config,
        platform="signal",
        runtime_profile_key=runtime_profile_key,
    )
    account_number = _nonempty_text(getattr(signal_cfg, "account", None))
    event_type = _signal_event_type(envelope)
    event_id = _signal_event_id(envelope)
    sender = _signal_sender(envelope)
    room_id = sender
    return [
        MessagingIngressStageEntry(
            ipc_command="signal_ingress_event",
            event=MessagingIngressEvent(
                version=1,
                platform="signal",
                runtime_profile_key=runtime_profile_key,
                source_mode="receive_loop",
                event_type=event_type,
                event_id=event_id,
                dedupe_key=_dedupe_key(event_type, event_id, envelope),
                identifier_type="account_number",
                identifier_value=account_number,
                room_id=room_id,
                sender=sender,
                payload=dict(payload),
                provider_context={
                    "runtime_profile_key": runtime_profile_key,
                    "account_number": account_number,
                },
            ),
        )
    ]
