"""Provides an implementation of IIPCExtension for Signal REST API support."""

__all__ = ["SignalRestAPIIPCExtension"]

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.client.signal import ISignalClient
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
    get_platform_profile_section,
    runtime_profile_key_from_ingress_route,
    runtime_profile_scope,
)
from mugen.core.service.ingress_routing import (
    DefaultIngressRoutingService,
)
from mugen.core.utility.processing_signal import (
    PROCESSING_STATE_START,
    PROCESSING_STATE_STOP,
    normalize_processing_state,
)


def _signal_client_provider():
    return di.container.signal_client


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


class SignalRestAPIIPCExtension(IIPCExtension):
    """An implementation of IIPCExtension for Signal REST API support."""

    _event_dedup_table = "signal_restapi_event_dedup"
    _event_dead_letter_table = "signal_restapi_event_dead_letter"
    _default_event_dedup_ttl_seconds = 86400

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        config: SimpleNamespace | None = None,
        logging_gateway: ILoggingGateway | None = None,
        relational_storage_gateway: IRelationalStorageGateway | None = None,
        messaging_service: IMessagingService | None = None,
        user_service: IUserService | None = None,
        signal_client: ISignalClient | None = None,
        ingress_routing_service: IIngressRoutingService | None = None,
    ) -> None:
        self._client = signal_client if signal_client is not None else _signal_client_provider()
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
            "signal_ingress_event",
            "signal_restapi_event",
        ]

    @property
    def platforms(self) -> list[str]:
        """Get the platform that the extension is targeting."""
        return ["signal"]

    def _ingress_router(self) -> IIngressRoutingService:
        if self._ingress_routing_service is not None:
            return self._ingress_routing_service
        self._ingress_routing_service = DefaultIngressRoutingService(
            relational_storage_gateway=self._relational_storage_gateway,
            logging_gateway=self._logging_gateway,
        )
        return self._ingress_routing_service

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        raw_value = getattr(
            getattr(getattr(self._config, "signal", SimpleNamespace()), "receive", None),
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
            self._increment_metric("signal.ipc.dead_letter.write_success")
        except SQLAlchemyError as exc:
            self._increment_metric("signal.ipc.dead_letter.write_failure")
            self._logging_gateway.error(
                "Failed to write Signal dead-letter event."
                f" reason_code={reason_code}"
                f" error={type(exc).__name__}: {exc}"
            )

    async def _is_duplicate_event(self, event_type: str, event_payload: dict) -> bool:
        dedupe_key = self._build_event_dedupe_key(event_type, event_payload)
        event_id = self._extract_event_id(event_payload)
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
            self._increment_metric("signal.ipc.dedupe.miss")
            return False
        except IntegrityError:
            self._increment_metric("signal.ipc.dedupe.hit")
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
            self._increment_metric("signal.ipc.dedupe.error")
            self._logging_gateway.error(
                "Signal dedupe lookup failed."
                f" error={type(exc).__name__}: {exc}"
            )
            return False

    @staticmethod
    def _extract_envelope(payload: dict) -> dict | None:
        if not isinstance(payload, dict):
            return None
        if payload.get("method") != "receive":
            return None
        params = payload.get("params")
        if not isinstance(params, dict):
            return None
        envelope = params.get("envelope")
        if not isinstance(envelope, dict):
            return None
        return envelope

    @staticmethod
    def _extract_event_id(envelope: dict) -> str | None:
        timestamp = envelope.get("timestamp")
        source_uuid = envelope.get("sourceUuid")
        if isinstance(timestamp, int | float):
            if isinstance(source_uuid, str) and source_uuid != "":
                return f"{source_uuid}:{int(timestamp)}"
            source = envelope.get("sourceNumber") or envelope.get("source")
            if isinstance(source, str) and source != "":
                return f"{source}:{int(timestamp)}"
            return str(int(timestamp))
        return None

    @staticmethod
    def _extract_sender(envelope: dict) -> str | None:
        source_number = envelope.get("sourceNumber")
        if isinstance(source_number, str) and source_number.strip() != "":
            return source_number.strip()
        source_uuid = envelope.get("sourceUuid")
        if isinstance(source_uuid, str) and source_uuid.strip() != "":
            return source_uuid.strip()
        source = envelope.get("source")
        if isinstance(source, str) and source.strip() != "":
            return source.strip()
        return None

    @staticmethod
    def _coerce_nonempty_string(value: object) -> str | None:
        if isinstance(value, str) and value.strip() != "":
            return value.strip()
        return None

    def _signal_account_number(
        self,
        runtime_profile_key: str | None = None,
    ) -> str | None:
        signal_cfg = getattr(self._config, "signal", SimpleNamespace())
        if runtime_profile_key is not None:
            try:
                signal_cfg = get_platform_profile_section(
                    self._config,
                    platform="signal",
                    runtime_profile_key=runtime_profile_key,
                )
            except KeyError:
                return None
        account_cfg = getattr(signal_cfg, "account", SimpleNamespace())
        return self._coerce_nonempty_string(getattr(account_cfg, "number", None))

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
            "platform": "signal",
            "channel_key": "signal",
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
        account_number: str | None,
        webhook_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        claims = {"account_number": account_number} if account_number is not None else {}
        resolution = await self._ingress_router().resolve(
            IngressRouteRequest(
                platform="signal",
                channel_key="signal",
                identifier_type="account_number",
                identifier_value=account_number,
                claims=claims,
            )
        )
        try:
            ingress_route = resolve_ingress_route_context(
                platform="signal",
                channel_key="signal",
                routing=resolution,
                source="signal.ingress_routing",
                identifier_claims=claims,
                global_fallback_reasons=(),
            )
        except ContextScopeResolutionError as exc:
            self._increment_metric("signal.ipc.route.unresolved")
            reason_code = str(exc.reason_code or "route_unresolved")
            await self._record_dead_letter(
                event_type="webhook",
                event_payload=webhook_payload,
                reason_code="route_unresolved",
                error_message=str(exc),
            )
            self._logging_gateway.warning(
                "Dropped Signal ingress due to unresolved route "
                f"reason_code={reason_code} account_number={account_number!r}."
            )
            return None
        return ingress_route

    @staticmethod
    def _extract_room_id(envelope: dict, sender: str) -> str:
        data_message = envelope.get("dataMessage")
        if isinstance(data_message, dict):
            group_info = data_message.get("groupInfo")
            if isinstance(group_info, dict):
                group_id = group_info.get("groupId")
                if isinstance(group_id, str) and group_id.strip() != "":
                    return group_id.strip()
        return sender

    @staticmethod
    def _extract_text_message(envelope: dict) -> str | None:
        data_message = envelope.get("dataMessage")
        if not isinstance(data_message, dict):
            return None
        message = data_message.get("message")
        if isinstance(message, str) and message.strip() != "":
            return message
        return None

    @staticmethod
    def _extract_reaction(envelope: dict) -> dict | None:
        data_message = envelope.get("dataMessage")
        if not isinstance(data_message, dict):
            return None
        reaction = data_message.get("reaction")
        if not isinstance(reaction, dict):
            return None
        emoji = reaction.get("emoji")
        if not isinstance(emoji, str) or emoji.strip() == "":
            return None
        return reaction

    @staticmethod
    def _extract_attachments(envelope: dict) -> list[dict]:
        data_message = envelope.get("dataMessage")
        if not isinstance(data_message, dict):
            return []
        attachments = data_message.get("attachments")
        if not isinstance(attachments, list):
            return []
        return [item for item in attachments if isinstance(item, dict)]

    @staticmethod
    def _classify_event_type(envelope: dict) -> str:
        if SignalRestAPIIPCExtension._extract_reaction(envelope) is not None:
            return "reaction"
        if SignalRestAPIIPCExtension._extract_text_message(envelope) is not None:
            return "message"
        if SignalRestAPIIPCExtension._extract_attachments(envelope):
            return "message"
        if isinstance(envelope.get("receiptMessage"), dict):
            return "receipt"
        return "unknown"

    async def _emit_processing_signal(
        self,
        *,
        recipient: str,
        message_id: str | None,
        state: str,
    ) -> None:
        _ = message_id
        emitter = getattr(self._client, "emit_processing_signal", None)
        if callable(emitter) is not True:
            return
        try:
            normalized_state = normalize_processing_state(state)
            result = await emitter(
                recipient,
                state=normalized_state,
            )
            if result is False:
                self._logging_gateway.warning(
                    "Signal thinking signal reported failure "
                    f"(recipient={recipient} state={normalized_state})."
                )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "Signal thinking signal raised unexpectedly "
                f"(recipient={recipient} state={state}): {exc}"
            )

    async def _register_sender_if_unknown(
        self,
        *,
        sender: str,
        room_id: str,
    ) -> None:
        known_users = await self._user_service.get_known_users_list()
        known_users = known_users if isinstance(known_users, dict) else {}
        if sender in known_users.keys():
            return
        self._logging_gateway.debug(f"New Signal contact: {sender}")
        await self._user_service.add_known_user(sender, sender, room_id)

    @staticmethod
    def _attachment_as_base64_data_url(file_payload: dict) -> str | None:
        if not isinstance(file_payload, dict):
            return None
        inline_data = file_payload.get("base64")
        if isinstance(inline_data, str) and inline_data.strip() != "":
            return inline_data

        file_path = file_payload.get("path")
        if not isinstance(file_path, str) or file_path.strip() == "":
            return None
        path = Path(file_path.strip())
        if path.is_file() is not True:
            return None

        mime_type = file_payload.get("mime_type")
        if not isinstance(mime_type, str) or mime_type.strip() == "":
            mime_type = "application/octet-stream"

        payload = path.read_bytes()
        encoded = base64.b64encode(payload).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    async def _send_response_to_user(
        self,
        response: dict,
        default_recipient: str,
    ) -> None:
        response_type = response.get("type")

        if response_type == "signal":
            op = str(response.get("op") or "").strip().lower()
            recipient = str(response.get("recipient") or default_recipient).strip()
            if op == "send_message":
                text = response.get("text")
                if not isinstance(text, str) or text.strip() == "":
                    self._logging_gateway.error(
                        "Missing Signal send_message text payload."
                    )
                    return
                await self._client.send_text_message(
                    recipient=recipient,
                    text=text,
                )
                return
            if op == "send_reaction":
                reaction = str(response.get("reaction") or "").strip()
                target_author = str(response.get("target_author") or "").strip()
                timestamp = response.get("timestamp")
                if (
                    reaction == ""
                    or target_author == ""
                    or isinstance(timestamp, bool)
                    or not isinstance(timestamp, int)
                ):
                    self._logging_gateway.error(
                        "Invalid Signal send_reaction payload."
                    )
                    return
                await self._client.send_reaction(
                    recipient=recipient,
                    reaction=reaction,
                    target_author=target_author,
                    timestamp=timestamp,
                    remove=bool(response.get("remove", False)),
                )
                return
            if op == "send_receipt":
                receipt_type = str(response.get("receipt_type") or "").strip()
                timestamp = response.get("timestamp")
                if (
                    receipt_type == ""
                    or isinstance(timestamp, bool)
                    or not isinstance(timestamp, int)
                ):
                    self._logging_gateway.error(
                        "Invalid Signal send_receipt payload."
                    )
                    return
                await self._client.send_receipt(
                    recipient=recipient,
                    receipt_type=receipt_type,
                    timestamp=timestamp,
                )
                return
            self._logging_gateway.error(f"Unsupported Signal response op: {op}.")
            return

        recipient = str(response.get("recipient") or default_recipient).strip()
        if response_type == "text":
            content = response.get("content")
            if not isinstance(content, str) or content.strip() == "":
                self._logging_gateway.error("Missing text content in response payload.")
                return
            await self._client.send_text_message(
                recipient=recipient,
                text=content,
            )
            return

        if response_type in {"audio", "file", "image", "video"}:
            file_payload = response.get("file")
            encoded = self._attachment_as_base64_data_url(file_payload)
            if encoded is None:
                self._logging_gateway.error("Missing attachment payload in response.")
                return
            message = response.get("content")
            if not isinstance(message, str):
                message = None
            await self._client.send_media_message(
                recipient=recipient,
                message=message,
                base64_attachments=[encoded],
            )
            return

        self._logging_gateway.error(f"Unsupported response type: {response_type}.")

    async def _dispatch_attachments(
        self,
        *,
        sender: str,
        room_id: str,
        attachments: list[dict],
        ingress_route: dict[str, Any] | None = None,
    ) -> list[dict]:
        ingress_route = self._normalize_ingress_route(ingress_route)
        responses: list[dict] = []
        for attachment in attachments:
            attachment_id = attachment.get("id")
            if not isinstance(attachment_id, str) or attachment_id.strip() == "":
                continue

            downloaded = await self._client.download_attachment(attachment_id.strip())
            if not isinstance(downloaded, dict):
                continue

            mime_type = downloaded.get("mime_type")
            if not isinstance(mime_type, str):
                mime_type = "application/octet-stream"

            if mime_type.startswith("audio/"):
                next_responses = await self._messaging_service.handle_audio_message(
                    "signal",
                    room_id=room_id,
                    sender=sender,
                    message=self._merge_ingress_metadata(
                        payload={"file": downloaded},
                        ingress_route=ingress_route,
                    ),
                )
            elif mime_type.startswith("image/"):
                next_responses = await self._messaging_service.handle_image_message(
                    "signal",
                    room_id=room_id,
                    sender=sender,
                    message=self._merge_ingress_metadata(
                        payload={"file": downloaded},
                        ingress_route=ingress_route,
                    ),
                )
            elif mime_type.startswith("video/"):
                next_responses = await self._messaging_service.handle_video_message(
                    "signal",
                    room_id=room_id,
                    sender=sender,
                    message=self._merge_ingress_metadata(
                        payload={"file": downloaded},
                        ingress_route=ingress_route,
                    ),
                )
            else:
                next_responses = await self._messaging_service.handle_file_message(
                    "signal",
                    room_id=room_id,
                    sender=sender,
                    message=self._merge_ingress_metadata(
                        payload={"file": downloaded},
                        ingress_route=ingress_route,
                    ),
                )

            if isinstance(next_responses, list):
                responses.extend([item for item in next_responses if isinstance(item, dict)])
        return responses

    async def _handle_message_event(
        self,
        envelope: dict,
        ingress_route: dict[str, Any] | None = None,
    ) -> None:
        ingress_route = self._normalize_ingress_route(ingress_route)
        sender = self._extract_sender(envelope)
        if sender is None:
            self._logging_gateway.error("Signal event missing sender identity.")
            return
        room_id = self._extract_room_id(envelope, sender)
        await self._register_sender_if_unknown(sender=sender, room_id=room_id)
        await self._emit_processing_signal(
            recipient=room_id,
            message_id=self._extract_event_id(envelope),
            state=PROCESSING_STATE_START,
        )

        responses: list[dict] = []
        text = self._extract_text_message(envelope)
        reaction = self._extract_reaction(envelope)
        attachments = self._extract_attachments(envelope)

        try:
            if isinstance(text, str):
                next_responses = await self._messaging_service.handle_text_message(
                    "signal",
                    room_id=room_id,
                    sender=sender,
                    message=text,
                    message_context=self._compose_message_context(
                        ingress_route=ingress_route,
                    ),
                )
                if isinstance(next_responses, list):
                    responses.extend([item for item in next_responses if isinstance(item, dict)])

            if isinstance(reaction, dict):
                emoji = reaction.get("emoji")
                if isinstance(emoji, str) and emoji.strip() != "":
                    next_responses = await self._messaging_service.handle_text_message(
                        "signal",
                        room_id=room_id,
                        sender=sender,
                        message=emoji,
                        message_context=self._compose_message_context(
                            ingress_route=ingress_route,
                            extra_context=[
                                {
                                    "type": "signal_reaction",
                                    "content": reaction,
                                }
                            ],
                        ),
                    )
                    if isinstance(next_responses, list):
                        responses.extend(
                            [item for item in next_responses if isinstance(item, dict)]
                        )

            if attachments:
                responses.extend(
                    await self._dispatch_attachments(
                        sender=sender,
                        room_id=room_id,
                        attachments=attachments,
                        ingress_route=ingress_route,
                    )
                )

            for response in responses:
                await self._send_response_to_user(response, room_id)
        finally:
            await self._emit_processing_signal(
                recipient=room_id,
                message_id=self._extract_event_id(envelope),
                state=PROCESSING_STATE_STOP,
            )

    async def _signal_restapi_event(self, request: IPCCommandRequest) -> None:
        payload = request.data
        if not isinstance(payload, dict):
            self._increment_metric("signal.ipc.event.malformed")
            await self._record_dead_letter(
                event_type="malformed",
                event_payload={"payload": payload},
                reason_code="invalid_payload_type",
            )
            return

        envelope = self._extract_envelope(payload)
        if envelope is None:
            self._increment_metric("signal.ipc.event.malformed")
            await self._record_dead_letter(
                event_type="malformed",
                event_payload=payload,
                reason_code="missing_envelope",
            )
            return

        runtime_profile_key = self._coerce_nonempty_string(
            payload.get("runtime_profile_key")
        )
        ingress_route = await self._resolve_ingress_route(
            account_number=self._signal_account_number(runtime_profile_key),
            webhook_payload=payload,
        )
        if ingress_route is None:
            return

        event_type = self._classify_event_type(envelope)
        if await self._is_duplicate_event(event_type, envelope):
            self._increment_metric("signal.ipc.event.duplicate")
            return

        try:
            with runtime_profile_scope(
                runtime_profile_key_from_ingress_route(ingress_route)
            ):
                if event_type in {"message", "reaction"}:
                    await self._handle_message_event(
                        envelope,
                        ingress_route,
                    )
                elif event_type == "receipt":
                    self._logging_gateway.debug("Signal receipt event observed.")
                else:
                    self._logging_gateway.debug("Signal event ignored (unsupported type).")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._increment_metric("signal.ipc.event.processed_failed")
            await self._record_dead_letter(
                event_type=event_type,
                event_payload=envelope,
                reason_code="processing_exception",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

        self._increment_metric("signal.ipc.event.processed_ok")

    async def _signal_ingress_event(self, request: IPCCommandRequest) -> None:
        payload = request.data if isinstance(request.data, dict) else {}
        envelope = self._extract_envelope(payload.get("payload")) if isinstance(payload.get("payload"), dict) else None
        if envelope is None:
            raise TypeError("Signal ingress payload.event must include params.envelope.")

        provider_context = payload.get("provider_context")
        provider_context = provider_context if isinstance(provider_context, dict) else {}
        runtime_profile_key = self._coerce_nonempty_string(
            payload.get("runtime_profile_key")
        ) or self._coerce_nonempty_string(provider_context.get("runtime_profile_key"))
        account_number = self._coerce_nonempty_string(
            provider_context.get("account_number")
        ) or self._signal_account_number(runtime_profile_key)
        ingress_route = None
        if account_number is not None:
            ingress_route = await self._resolve_ingress_route(
                account_number=account_number,
                webhook_payload=payload,
            )
        if ingress_route is None and isinstance(provider_context.get("ingress_route"), dict):
            ingress_route = provider_context.get("ingress_route")

        event_type = str(payload.get("event_type") or self._classify_event_type(envelope))
        runtime_profile_key = (
            runtime_profile_key
            or runtime_profile_key_from_ingress_route(ingress_route)
        )
        with runtime_profile_scope(runtime_profile_key):
            if event_type in {"message", "reaction"}:
                await self._handle_message_event(
                    envelope,
                    ingress_route,
                )
            elif event_type == "receipt":
                self._logging_gateway.debug("Signal receipt event observed.")
            else:
                self._logging_gateway.debug("Signal event ignored (unsupported type).")

    async def process_ipc_command(self, request: IPCCommandRequest) -> IPCHandlerResult:
        handler_name = type(self).__name__
        match request.command:
            case "signal_ingress_event":
                await self._signal_ingress_event(request)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case "signal_restapi_event":
                await self._signal_restapi_event(request)
                return IPCHandlerResult(
                    handler=handler_name,
                    response={"response": "OK"},
                )
            case _:
                return IPCHandlerResult(
                    handler=handler_name,
                    ok=False,
                    code="not_found",
                    error=f"Unknown command: {request.command}",
                )
