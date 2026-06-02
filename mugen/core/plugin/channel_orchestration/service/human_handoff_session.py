"""Provides human handoff session actions and runtime helpers."""

from __future__ import annotations

__all__ = ["HumanHandoffSessionService"]

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from typing import Any, Mapping
import uuid

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core import di
from mugen.core.contract.context import ContextScope, ContextTurnRequest
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.contract.gateway.storage.rdbms.types import ScalarFilter, ScalarFilterOp
from mugen.core.plugin.channel_orchestration.api.validation import (
    ActivateHandoffValidation,
    DeactivateHandoffValidation,
    HumanReplyValidation,
    ListTranscriptValidation,
)
from mugen.core.plugin.channel_orchestration.contract.service import (
    HumanHandoffReleased,
)
from mugen.core.plugin.channel_orchestration.domain import (
    HumanHandoffSessionDE,
    OrchestrationEventDE,
)
from mugen.core.plugin.channel_orchestration.service.orchestration_event import (
    OrchestrationEventService,
)
from mugen.core.plugin.context_engine.service.runtime import (
    ContextEventLogService,
    ContextStateSnapshotService,
)
from mugen.core.utility.client_profile_runtime import client_profile_scope
from mugen.core.utility.context_runtime import scope_key


class HumanHandoffSessionService(IRelationalService[HumanHandoffSessionDE]):
    """A CRUD/action service for human takeover of conversation scopes."""

    _CONTEXT_EVENT_TABLE = "context_engine_context_event_log"
    _CONTEXT_SNAPSHOT_TABLE = "context_engine_context_state_snapshot"
    _EVENT_TABLE = "channel_orchestration_orchestration_event"
    _DEFAULT_TRANSCRIPT_LIMIT = 40
    _MAX_TRANSCRIPT_LIMIT = 200
    _EVENT_SEQUENCE_ATTEMPTS = 3
    _SNAPSHOT_UPDATE_ATTEMPTS = 3
    _STREAM_REPLAY_LIMIT = 100
    _STREAM_POLL_SECONDS = 1.0
    _STREAM_KEEPALIVE_SECONDS = 15.0

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=HumanHandoffSessionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._context_event_service = ContextEventLogService(
            table=self._CONTEXT_EVENT_TABLE,
            rsg=rsg,
        )
        self._context_snapshot_service = ContextStateSnapshotService(
            table=self._CONTEXT_SNAPSHOT_TABLE,
            rsg=rsg,
        )
        self._event_service = OrchestrationEventService(
            table=self._EVENT_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: object) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @classmethod
    def _delivery_error(cls, error: BaseException) -> str:
        message = f"{type(error).__name__}: {error}".strip()
        return message[:1024] or type(error).__name__

    @classmethod
    def _scope_from_values(
        cls,
        *,
        tenant_id: uuid.UUID | str,
        platform: str,
        channel_id: str | None,
        room_id: str | None,
        sender_id: str | None,
        conversation_id: str | None,
    ) -> ContextScope:
        return ContextScope(
            tenant_id=str(tenant_id),
            platform=platform,
            channel_id=channel_id,
            room_id=room_id,
            sender_id=sender_id,
            conversation_id=conversation_id,
        )

    @classmethod
    def _scope_payload(
        cls,
        *,
        tenant_id: uuid.UUID,
        platform: str,
        room_id: str,
        sender_id: str,
        channel_id: str | None = None,
        conversation_id: str | None = None,
        client_profile_id: uuid.UUID | None = None,
        service_route_key: str | None = None,
    ) -> dict[str, Any]:
        scope = cls._scope_from_values(
            tenant_id=tenant_id,
            platform=platform,
            channel_id=channel_id,
            room_id=room_id,
            sender_id=sender_id,
            conversation_id=conversation_id,
        )
        return {
            "tenant_id": tenant_id,
            "scope_key": scope_key(scope),
            "platform": scope.platform,
            "channel_id": scope.channel_id,
            "room_id": scope.room_id,
            "sender_id": scope.sender_id,
            "conversation_id": scope.conversation_id,
            "client_profile_id": client_profile_id,
            "service_route_key": service_route_key,
        }

    @staticmethod
    def _request_client_profile_id(request: ContextTurnRequest) -> uuid.UUID | None:
        ingress_route = request.ingress_metadata.get("ingress_route")
        raw_value = None
        if isinstance(ingress_route, Mapping):
            raw_value = ingress_route.get("client_profile_id")
        if raw_value in [None, ""]:
            raw_value = request.ingress_metadata.get("client_profile_id")
        if raw_value in [None, ""]:
            return None
        try:
            return uuid.UUID(str(raw_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _request_service_route_key(request: ContextTurnRequest) -> str | None:
        ingress_route = request.ingress_metadata.get("ingress_route")
        if isinstance(ingress_route, Mapping):
            value = HumanHandoffSessionService._normalize_optional_text(
                ingress_route.get("service_route_key")
            )
            if value is not None:
                return value
        return HumanHandoffSessionService._normalize_optional_text(
            request.ingress_metadata.get("service_route_key")
        )

    async def active_session_for_request(
        self,
        request: ContextTurnRequest,
    ) -> HumanHandoffSessionDE | None:
        """Return the active session for a context request, if any."""
        try:
            return await self._active_session(
                tenant_id=uuid.UUID(str(request.scope.tenant_id)),
                scope_key_value=scope_key(request.scope),
            )
        except (TypeError, ValueError):
            return None

    async def activate_for_turn(
        self,
        request: ContextTurnRequest,
        *,
        reason: str | None = None,
        owner_user_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HumanHandoffSessionDE:
        """Activate handoff for an assistant-requested turn."""
        tenant_id = uuid.UUID(str(request.scope.tenant_id))
        payload = {
            "tenant_id": tenant_id,
            "scope_key": scope_key(request.scope),
            "platform": request.scope.platform,
            "channel_id": request.scope.channel_id,
            "room_id": request.scope.room_id,
            "sender_id": request.scope.sender_id,
            "conversation_id": request.scope.conversation_id,
            "client_profile_id": self._request_client_profile_id(request),
            "service_route_key": self._request_service_route_key(request),
            "status": "active",
            "reason": self._normalize_optional_text(reason),
            "owner_user_id": owner_user_id,
            "activated_at": self._now_utc(),
            "deactivated_at": None,
            "deactivated_by_user_id": None,
            "deactivation_reason": None,
            "last_user_message_at": None,
            "last_transcript_sequence_no": None,
            "last_human_reply_at": None,
            "last_delivery_status": None,
            "last_delivery_error": None,
            "attributes": dict(metadata or {}),
        }
        session = await self._upsert_active_session(payload=payload)
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=session,
            actor_user_id=owner_user_id,
            event_type="activate_handoff",
            decision="active",
            reason=reason,
            payload={"source": "assistant"},
        )
        return session

    async def append_user_turn(self, request: ContextTurnRequest) -> None:
        """Persist an inbound user turn while handoff suppresses AI handling."""
        occurred_at = self._now_utc()
        tenant_id = uuid.UUID(str(request.scope.tenant_id))
        session = await self.active_session_for_request(request)
        sequence_no = await self._append_context_event(
            tenant_id=tenant_id,
            scope_key_value=scope_key(request.scope),
            role="user",
            content=request.user_message,
            message_id=request.message_id,
            trace_id=request.trace_id,
            source="human_handoff_user_turn",
            scope=request.scope,
            session=session,
            occurred_at=occurred_at,
        )
        if session is None or session.id is None:
            return
        updated = await self._update_transcript_markers(
            tenant_id=tenant_id,
            session=session,
            sequence_no=sequence_no,
            last_user_message_at=occurred_at,
        )
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=updated or session,
            actor_user_id=None,
            event_type="handoff.transcript_appended",
            decision="user",
            reason=None,
            payload={
                "role": "user",
                "sequence_no": sequence_no,
                "message_id": request.message_id,
                "trace_id": request.trace_id,
                "source": "human_handoff_user_turn",
            },
            occurred_at=occurred_at,
        )

    async def action_activate_handoff(
        self,
        *,
        tenant_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: ActivateHandoffValidation,
    ) -> tuple[dict[str, str], int]:
        """Activate or reactivate human handoff for a supplied scope."""
        _ = where
        payload = self._scope_payload(
            tenant_id=tenant_id,
            platform=data.platform,
            channel_id=data.channel_id,
            room_id=data.room_id,
            sender_id=data.sender_id,
            conversation_id=data.conversation_id,
            client_profile_id=data.client_profile_id,
            service_route_key=data.service_route_key,
        )
        payload.update(
            {
                "status": "active",
                "owner_user_id": auth_user_id,
                "reason": data.reason,
                "activated_at": self._now_utc(),
                "deactivated_at": None,
                "deactivated_by_user_id": None,
                "deactivation_reason": None,
                "last_user_message_at": None,
                "last_transcript_sequence_no": None,
                "last_human_reply_at": None,
                "last_delivery_status": None,
                "last_delivery_error": None,
                "attributes": dict(data.metadata or {}),
            }
        )
        session = await self._upsert_active_session(payload=payload)
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=session,
            actor_user_id=auth_user_id,
            event_type="activate_handoff",
            decision="active",
            reason=data.reason,
            payload={"source": "operator"},
        )
        return {
            "Decision": "active",
            "HumanHandoffSessionId": str(session.id),
            "ScopeKey": str(session.scope_key),
        }, 200

    async def action_deactivate_handoff(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: DeactivateHandoffValidation,
    ) -> tuple[dict[str, str], int]:
        """Deactivate a handoff session and resume normal AI handling."""
        session = await self._get_session_for_action(where=where)
        if session.status == "inactive":
            return {"Decision": "inactive"}, 200

        now = self._now_utc()
        updated_session = await self.update(
            {"tenant_id": tenant_id, "id": entity_id},
            {
                "status": "inactive",
                "deactivated_at": now,
                "deactivated_by_user_id": auth_user_id,
                "deactivation_reason": data.reason,
            },
        )
        release_session = self._released_session(
            session=updated_session or session,
            deactivated_at=now,
            deactivated_by_user_id=auth_user_id,
            deactivation_reason=data.reason,
        )
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=release_session,
            actor_user_id=auth_user_id,
            event_type="deactivate_handoff",
            decision="inactive",
            reason=data.reason,
            payload=None,
        )
        hook_decision, hook_reason = await self._notify_release_hook(
            tenant_id=tenant_id,
            session=release_session,
            actor_user_id=auth_user_id,
            reason=data.reason,
            deactivated_at=now,
        )
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=release_session,
            actor_user_id=auth_user_id,
            event_type="handoff_release_hook",
            decision=hook_decision,
            reason=hook_reason,
            payload=self._release_hook_payload(session=release_session),
        )
        return {"Decision": "inactive"}, 200

    async def action_human_reply(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: HumanReplyValidation,
    ) -> tuple[dict[str, str | None], int]:
        """Append and deliver one human-authored assistant reply."""
        session = await self._get_session_for_action(where=where)
        if session.status != "active":
            abort(409, "Human handoff session is not active.")

        occurred_at = self._now_utc()
        sequence_no = await self._append_context_event(
            tenant_id=tenant_id,
            scope_key_value=str(session.scope_key),
            role="assistant",
            content=data.content,
            message_id=data.message_id,
            trace_id=data.trace_id,
            source="human_handoff",
            session=session,
            occurred_at=occurred_at,
        )

        delivery_status, delivery_error = await self._deliver_human_reply(
            session=session,
            content=data.content,
            metadata=dict(data.metadata or {}),
        )
        updated_session = await self.update(
            {"tenant_id": tenant_id, "id": entity_id},
            {
                "last_human_reply_at": occurred_at,
                "last_transcript_sequence_no": sequence_no,
                "last_delivery_status": delivery_status,
                "last_delivery_error": delivery_error,
            },
        )
        event_session = updated_session or replace(
            session,
            last_human_reply_at=occurred_at,
            last_transcript_sequence_no=sequence_no,
            last_delivery_status=delivery_status,
            last_delivery_error=delivery_error,
        )
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=event_session,
            actor_user_id=auth_user_id,
            event_type="handoff.transcript_appended",
            decision="assistant",
            reason=None,
            payload={
                "role": "assistant",
                "sequence_no": sequence_no,
                "message_id": data.message_id,
                "trace_id": data.trace_id,
                "source": "human_handoff",
            },
            occurred_at=occurred_at,
        )
        await self._append_handoff_event(
            tenant_id=tenant_id,
            session=event_session,
            actor_user_id=auth_user_id,
            event_type="human_reply",
            decision=delivery_status,
            reason=delivery_error,
            payload={
                "sequence_no": sequence_no,
                "delivery_status": delivery_status,
                "delivery_error": delivery_error,
                "message_id": data.message_id,
                "trace_id": data.trace_id,
                "metadata": dict(data.metadata or {}),
            },
            occurred_at=occurred_at,
        )
        return {
            "Decision": "replied",
            "DeliveryStatus": delivery_status,
            "DeliveryError": delivery_error,
        }, 200

    async def action_list_transcript(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: ListTranscriptValidation,
    ) -> tuple[dict[str, Any], int]:
        """Return a bounded transcript for a handoff session."""
        _ = entity_id
        _ = auth_user_id
        session = await self._get_session_for_action(where=where)
        limit = min(
            int(data.limit or self._DEFAULT_TRANSCRIPT_LIMIT),
            self._MAX_TRANSCRIPT_LIMIT,
        )
        after_sequence_no = data.after_sequence_no
        filter_group = FilterGroup(
            where={
                "tenant_id": tenant_id,
                "scope_key": str(session.scope_key),
            }
        )
        order_by = [OrderBy("sequence_no", descending=True)]
        query_limit = limit
        if after_sequence_no is not None:
            filter_group = FilterGroup(
                where={
                    "tenant_id": tenant_id,
                    "scope_key": str(session.scope_key),
                },
                scalar_filters=[
                    ScalarFilter(
                        "sequence_no",
                        ScalarFilterOp.GT,
                        int(after_sequence_no),
                    )
                ],
            )
            order_by = [OrderBy("sequence_no", descending=False)]
            query_limit = limit + 1
        rows = await self._context_event_service.list(
            filter_groups=[filter_group],
            order_by=order_by,
            limit=query_limit,
        )
        has_more = len(rows) > limit
        if has_more:
            rows = list(rows)[:limit]
        latest_rows = await self._context_event_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "scope_key": str(session.scope_key),
                    }
                )
            ],
            order_by=[OrderBy("sequence_no", descending=True)],
            limit=1,
        )
        latest_sequence_no = latest_rows[0].sequence_no if latest_rows else None
        ordered_rows = list(rows)
        if after_sequence_no is None:
            ordered_rows = list(reversed(ordered_rows))
        transcript = []
        for row in ordered_rows:
            transcript.append(
                {
                    "SequenceNo": row.sequence_no,
                    "Role": row.role,
                    "Content": row.content,
                    "MessageId": row.message_id,
                    "TraceId": row.trace_id,
                    "Source": row.source,
                    "OccurredAt": (
                        None
                        if row.occurred_at is None
                        else row.occurred_at.isoformat()
                    ),
                }
            )
        return {
            "Items": transcript,
            "Count": len(transcript),
            "LatestSequenceNo": latest_sequence_no,
            "HasMore": has_more,
        }, 200

    async def _get_session_for_action(self, *, where: dict) -> HumanHandoffSessionDE:
        try:
            session = await self.get(where)
        except SQLAlchemyError:
            abort(500)
        if session is None:
            abort(404, "Human handoff session not found.")
        return session

    @staticmethod
    def _released_session(
        *,
        session: HumanHandoffSessionDE,
        deactivated_at: datetime,
        deactivated_by_user_id: uuid.UUID | None,
        deactivation_reason: str | None,
    ) -> HumanHandoffSessionDE:
        return replace(
            session,
            status="inactive",
            deactivated_at=deactivated_at,
            deactivated_by_user_id=deactivated_by_user_id,
            deactivation_reason=deactivation_reason,
        )

    @staticmethod
    def _release_hook_payload(
        *,
        session: HumanHandoffSessionDE,
    ) -> dict[str, Any]:
        client_profile_id = session.client_profile_id
        return {
            "platform": session.platform,
            "channel_id": session.channel_id,
            "room_id": session.room_id,
            "sender_id": session.sender_id,
            "conversation_id": session.conversation_id,
            "client_profile_id": (
                None if client_profile_id is None else str(client_profile_id)
            ),
            "service_route_key": session.service_route_key,
        }

    async def _update_transcript_markers(
        self,
        *,
        tenant_id: uuid.UUID,
        session: HumanHandoffSessionDE,
        sequence_no: int,
        last_user_message_at: datetime | None = None,
    ) -> HumanHandoffSessionDE | None:
        if session.id is None:
            return None
        changes: dict[str, Any] = {
            "last_transcript_sequence_no": sequence_no,
        }
        if last_user_message_at is not None:
            changes["last_user_message_at"] = last_user_message_at
        return await self.update(
            {"tenant_id": tenant_id, "id": session.id},
            changes,
        )

    async def _notify_release_hook(
        self,
        *,
        tenant_id: uuid.UUID,
        session: HumanHandoffSessionDE,
        actor_user_id: uuid.UUID | None,
        reason: str | None,
        deactivated_at: datetime,
    ) -> tuple[str, str | None]:
        registry = di.container.get_ext_service(
            di.EXT_SERVICE_HUMAN_HANDOFF_RELEASE_HOOKS,
            None,
        )
        if registry is None:
            return "not_configured", None

        release_event = HumanHandoffReleased(
            tenant_id=tenant_id,
            session=session,
            actor_user_id=actor_user_id,
            reason=reason,
            deactivated_at=deactivated_at,
        )
        try:
            decision = await registry.notify_release(release_event)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return "failed", self._delivery_error(exc)
        return self._normalize_optional_text(decision) or "sent", None

    async def stream_handoff_events(
        self,
        *,
        tenant_id: uuid.UUID,
        last_event_id: str | None = None,
        session_id: uuid.UUID | None = None,
        status: str | None = None,
    ):
        """Stream replay and live handoff events as SSE payload chunks."""
        session_id_text = None if session_id is None else str(session_id)
        status_filter = self._normalize_optional_text(status)
        cursor_event, reset_reason = await self._resolve_stream_cursor(
            tenant_id=tenant_id,
            last_event_id=last_event_id,
        )
        replay_events = []
        if cursor_event is not None:
            replay_events = await self._stream_events_since(
                tenant_id=tenant_id,
                cursor_event=cursor_event,
            )
        latest_event = cursor_event or await self._latest_stream_event(
            tenant_id=tenant_id,
        )
        highest_occurred_at = (
            latest_event.occurred_at
            if latest_event is not None
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        seen_event_ids = {
            event.id for event in replay_events if event.id is not None
        }
        if latest_event is not None and latest_event.id is not None:
            seen_event_ids.add(latest_event.id)

        async def _event_stream():
            next_ping_at = (
                asyncio.get_running_loop().time() + self._STREAM_KEEPALIVE_SECONDS
            )
            nonlocal highest_occurred_at
            if reset_reason is not None:
                yield self._format_sse_event(
                    self._stream_reset_payload(
                        tenant_id=tenant_id,
                        reason=reset_reason,
                    )
                )

            for event in replay_events:
                payload = self._stream_payload_for_event(
                    tenant_id=tenant_id,
                    event=event,
                    session_id_filter=session_id_text,
                    status_filter=status_filter,
                )
                if payload is None:
                    continue
                yield self._format_sse_event(payload)
                if event.occurred_at is not None:
                    highest_occurred_at = max(highest_occurred_at, event.occurred_at)

            while True:
                rows = await self._stream_events_after_timestamp(
                    tenant_id=tenant_id,
                    occurred_at=highest_occurred_at,
                )
                yielded = False
                for event in rows:
                    if event.id in seen_event_ids:
                        continue
                    if event.id is not None:
                        seen_event_ids.add(event.id)
                    payload = self._stream_payload_for_event(
                        tenant_id=tenant_id,
                        event=event,
                        session_id_filter=session_id_text,
                        status_filter=status_filter,
                    )
                    if event.occurred_at is not None:
                        highest_occurred_at = max(
                            highest_occurred_at,
                            event.occurred_at,
                        )
                    if payload is None:
                        continue
                    yielded = True
                    yield self._format_sse_event(payload)

                if yielded:
                    next_ping_at = (
                        asyncio.get_running_loop().time()
                        + self._STREAM_KEEPALIVE_SECONDS
                    )
                    continue

                loop_now = asyncio.get_running_loop().time()
                if loop_now >= next_ping_at:
                    yield ": ping\n\n"
                    next_ping_at = loop_now + self._STREAM_KEEPALIVE_SECONDS
                await asyncio.sleep(self._STREAM_POLL_SECONDS)

        return _event_stream()

    async def _resolve_stream_cursor(
        self,
        *,
        tenant_id: uuid.UUID,
        last_event_id: str | None,
    ) -> tuple[OrchestrationEventDE | None, str | None]:
        normalized = self._normalize_optional_text(last_event_id)
        if normalized is None:
            return None, None
        cursor_uuid = self._parse_stream_event_id(
            tenant_id=tenant_id,
            event_id=normalized,
        )
        if cursor_uuid is None:
            return None, "cursor_unavailable"
        cursor_event = await self._event_service.get(
            {"tenant_id": tenant_id, "id": cursor_uuid}
        )
        if cursor_event is None:
            return None, "cursor_unavailable"
        return cursor_event, None

    async def _latest_stream_event(
        self,
        *,
        tenant_id: uuid.UUID,
    ) -> OrchestrationEventDE | None:
        rows = await self._event_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "source": "human_handoff",
                    }
                )
            ],
            order_by=[
                OrderBy("occurred_at", descending=True),
                OrderBy("id", descending=True),
            ],
            limit=1,
        )
        return rows[0] if rows else None

    async def _stream_events_since(
        self,
        *,
        tenant_id: uuid.UUID,
        cursor_event: OrchestrationEventDE,
    ) -> list[OrchestrationEventDE]:
        if cursor_event.occurred_at is None:
            return []
        rows = await self._stream_events_after_timestamp(
            tenant_id=tenant_id,
            occurred_at=cursor_event.occurred_at,
            limit=self._STREAM_REPLAY_LIMIT + 1,
        )
        output: list[OrchestrationEventDE] = []
        cursor_seen = False
        for row in rows:
            if row.id == cursor_event.id:
                cursor_seen = True
                continue
            if not cursor_seen:
                continue
            output.append(row)
        return output[: self._STREAM_REPLAY_LIMIT]

    async def _stream_events_after_timestamp(
        self,
        *,
        tenant_id: uuid.UUID,
        occurred_at: datetime,
        limit: int | None = None,
    ) -> list[OrchestrationEventDE]:
        return list(
            await self._event_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "source": "human_handoff",
                        },
                        scalar_filters=[
                            ScalarFilter(
                                "occurred_at",
                                ScalarFilterOp.GTE,
                                occurred_at,
                            )
                        ],
                    )
                ],
                order_by=[
                    OrderBy("occurred_at", descending=False),
                    OrderBy("id", descending=False),
                ],
                limit=limit or self._STREAM_REPLAY_LIMIT,
            )
        )

    @staticmethod
    def _parse_stream_event_id(
        *,
        tenant_id: uuid.UUID,
        event_id: str,
    ) -> uuid.UUID | None:
        parts = event_id.rsplit(":", 1)
        raw_uuid = parts[-1]
        if len(parts) == 2 and parts[0] != str(tenant_id):
            return None
        try:
            return uuid.UUID(raw_uuid)
        except ValueError:
            return None

    @staticmethod
    def _stream_event_id(
        *,
        tenant_id: uuid.UUID,
        event: OrchestrationEventDE,
    ) -> str | None:
        if event.id is None:
            return None
        return f"{tenant_id}:{event.id}"

    @classmethod
    def _stream_reset_payload(
        cls,
        *,
        tenant_id: uuid.UUID,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "event_type": "handoff.stream_reset",
            "tenant_id": str(tenant_id),
            "reason": reason,
        }

    @classmethod
    def _stream_payload_for_event(
        cls,
        *,
        tenant_id: uuid.UUID,
        event: OrchestrationEventDE,
        session_id_filter: str | None,
        status_filter: str | None,
    ) -> dict[str, Any] | None:
        raw_payload = dict(event.payload or {})
        session_id = cls._normalize_optional_text(raw_payload.get("session_id"))
        if session_id is None:
            return None
        if session_id_filter is not None and session_id != session_id_filter:
            return None
        status = cls._normalize_optional_text(raw_payload.get("status"))
        if status_filter is not None and status != status_filter:
            return None
        event_type = cls._public_stream_event_type(event=event, payload=raw_payload)
        if event_type is None:
            return None
        occurred_at = event.occurred_at
        output: dict[str, Any] = {
            "event_id": cls._stream_event_id(tenant_id=tenant_id, event=event),
            "tenant_id": str(tenant_id),
            "session_id": session_id,
            "event_type": event_type,
            "occurred_at": None if occurred_at is None else occurred_at.isoformat(),
        }
        sequence_no = raw_payload.get("sequence_no")
        if sequence_no is not None:
            output["sequence_no"] = sequence_no
        delivery_status = raw_payload.get("delivery_status") or event.decision
        delivery_error = raw_payload.get("delivery_error") or event.reason
        if event_type in {"handoff.reply_delivered", "handoff.reply_failed"}:
            output["delivery_status"] = delivery_status
            output["delivery_error"] = delivery_error
        return output

    @classmethod
    def _public_stream_event_type(
        cls,
        *,
        event: OrchestrationEventDE,
        payload: dict[str, Any],
    ) -> str | None:
        event_type = cls._normalize_optional_text(event.event_type)
        if event_type == "activate_handoff":
            return "handoff.session_activated"
        if event_type == "deactivate_handoff":
            return "handoff.session_released"
        if event_type == "handoff_release_hook":
            return "handoff.session_updated"
        if event_type == "handoff.transcript_appended":
            return "handoff.transcript_appended"
        if event_type == "human_reply":
            decision = cls._normalize_optional_text(payload.get("delivery_status"))
            decision = decision or cls._normalize_optional_text(event.decision)
            if decision == "sent":
                return "handoff.reply_delivered"
            if decision == "failed":
                return "handoff.reply_failed"
        return None

    @staticmethod
    def _format_sse_event(payload: dict[str, Any]) -> str:
        event_type = str(payload.get("event_type") or "message")
        event_id = payload.get("event_id")
        lines = []
        if event_id is not None:
            lines.append(f"id: {event_id}")
        lines.append(f"event: {event_type}")
        lines.append(
            "data: "
            + json.dumps(
                payload,
                default=str,
                separators=(",", ":"),
            )
        )
        return "\n".join(lines) + "\n\n"

    async def _active_session(
        self,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
    ) -> HumanHandoffSessionDE | None:
        rows = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "scope_key": scope_key_value,
                        "status": "active",
                    }
                )
            ],
            order_by=[OrderBy("updated_at", descending=True)],
            limit=1,
        )
        return rows[0] if rows else None

    async def _upsert_active_session(
        self,
        *,
        payload: dict[str, Any],
    ) -> HumanHandoffSessionDE:
        tenant_id = payload["tenant_id"]
        scope_key_value = str(payload["scope_key"])
        active = await self._active_session(
            tenant_id=tenant_id,
            scope_key_value=scope_key_value,
        )
        if active is not None and active.id is not None:
            updated = await self.update(
                {"tenant_id": tenant_id, "id": active.id},
                payload,
            )
            return updated or active

        rows = await self.list(
            filter_groups=[
                FilterGroup(
                    where={"tenant_id": tenant_id, "scope_key": scope_key_value}
                )
            ],
            order_by=[OrderBy("updated_at", descending=True)],
            limit=1,
        )
        if rows and rows[0].id is not None:
            updated = await self.update(
                {"tenant_id": tenant_id, "id": rows[0].id},
                payload,
            )
            return updated or rows[0]
        return await self.create(payload)

    async def _append_context_event(
        self,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        role: str,
        content: Any,
        message_id: str | None,
        trace_id: str | None,
        source: str,
        scope: ContextScope | None = None,
        session: HumanHandoffSessionDE | None = None,
        occurred_at: datetime | None = None,
    ) -> int:
        sequence_no = None
        event_occurred_at = occurred_at or self._now_utc()
        for _attempt in range(self._EVENT_SEQUENCE_ATTEMPTS):
            latest = await self._context_event_service.list(
                filter_groups=[
                    FilterGroup(
                        where={
                            "tenant_id": tenant_id,
                            "scope_key": scope_key_value,
                        }
                    )
                ],
                order_by=[OrderBy("sequence_no", descending=True)],
                limit=1,
            )
            sequence_no = 1
            if latest:
                sequence_no = int(latest[0].sequence_no or 0) + 1
            try:
                await self._context_event_service.create(
                    {
                        "tenant_id": tenant_id,
                        "scope_key": scope_key_value,
                        "sequence_no": sequence_no,
                        "role": role,
                        "content": content,
                        "message_id": self._normalize_optional_text(message_id),
                        "trace_id": self._normalize_optional_text(trace_id),
                        "source": source,
                        "occurred_at": event_occurred_at,
                    }
                )
                break
            except IntegrityError:
                continue
        else:
            raise RuntimeError("Context event sequence allocation conflict.")

        await self._advance_context_snapshot(
            tenant_id=tenant_id,
            scope_key_value=scope_key_value,
            sequence_no=int(sequence_no or 1),
            role=role,
            content=content,
            message_id=message_id,
            trace_id=trace_id,
            source=source,
            scope=scope,
            session=session,
        )
        return int(sequence_no or 1)

    async def _advance_context_snapshot(
        self,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        sequence_no: int,
        role: str,
        content: Any,
        message_id: str | None,
        trace_id: str | None,
        source: str,
        scope: ContextScope | None,
        session: HumanHandoffSessionDE | None,
    ) -> None:
        next_revision = max((int(sequence_no) + 1) // 2, 1)
        for _attempt in range(self._SNAPSHOT_UPDATE_ATTEMPTS):
            existing = await self._context_snapshot_service.get(
                {"tenant_id": tenant_id, "scope_key": scope_key_value}
            )
            payload = self._context_snapshot_payload(
                tenant_id=tenant_id,
                scope_key_value=scope_key_value,
                existing=existing,
                next_revision=next_revision,
                sequence_no=sequence_no,
                role=role,
                content=content,
                message_id=message_id,
                trace_id=trace_id,
                source=source,
                scope=scope,
                session=session,
            )
            if existing is None or existing.id is None:
                try:
                    await self._context_snapshot_service.create(payload)
                    return
                except IntegrityError:
                    continue

            updater = getattr(
                self._context_snapshot_service,
                "update_with_row_version",
                None,
            )
            updated = None
            if callable(updater) and isinstance(existing.row_version, int):
                updated = await updater(
                    {"tenant_id": tenant_id, "id": existing.id},
                    expected_row_version=existing.row_version,
                    changes=payload,
                )
            else:
                updated = await self._context_snapshot_service.update(
                    {"tenant_id": tenant_id, "id": existing.id},
                    payload,
                )
            if updated is not None:
                return

        raise RuntimeError("Context snapshot revision update conflict.")

    @classmethod
    def _context_snapshot_payload(
        cls,
        *,
        tenant_id: uuid.UUID,
        scope_key_value: str,
        existing,
        next_revision: int,
        sequence_no: int,
        role: str,
        content: Any,
        message_id: str | None,
        trace_id: str | None,
        source: str,
        scope: ContextScope | None,
        session: HumanHandoffSessionDE | None,
    ) -> dict[str, Any]:
        current_revision = int(getattr(existing, "revision", None) or 0)
        revision = max(current_revision, next_revision)
        attributes = dict(getattr(existing, "attributes", None) or {})
        attributes["human_handoff"] = {
            "last_role": role,
            "last_source": source,
            "last_sequence_no": sequence_no,
        }

        return {
            "tenant_id": tenant_id,
            "scope_key": scope_key_value,
            "platform": cls._snapshot_scope_value("platform", existing, scope, session),
            "channel_id": cls._snapshot_scope_value(
                "channel_id",
                existing,
                scope,
                session,
            ),
            "room_id": cls._snapshot_scope_value("room_id", existing, scope, session),
            "sender_id": cls._snapshot_scope_value(
                "sender_id",
                existing,
                scope,
                session,
            ),
            "conversation_id": cls._snapshot_scope_value(
                "conversation_id",
                existing,
                scope,
                session,
            ),
            "case_id": getattr(existing, "case_id", None),
            "workflow_id": getattr(existing, "workflow_id", None),
            "current_objective": cls._snapshot_objective(
                existing=existing,
                role=role,
                content=content,
            ),
            "entities": dict(getattr(existing, "entities", None) or {}),
            "constraints": list(getattr(existing, "constraints", None) or []),
            "unresolved_slots": list(
                getattr(existing, "unresolved_slots", None) or []
            ),
            "commitments": list(getattr(existing, "commitments", None) or []),
            "safety_flags": list(getattr(existing, "safety_flags", None) or []),
            "routing": dict(getattr(existing, "routing", None) or {}),
            "summary": getattr(existing, "summary", None),
            "revision": revision,
            "last_message_id": cls._normalize_optional_text(message_id),
            "last_trace_id": cls._normalize_optional_text(trace_id),
            "attributes": attributes,
        }

    @staticmethod
    def _snapshot_scope_value(
        field_name: str,
        existing,
        scope: ContextScope | None,
        session: HumanHandoffSessionDE | None,
    ) -> str | None:
        value = getattr(existing, field_name, None)
        if value is not None:
            return value
        if scope is not None:
            value = getattr(scope, field_name, None)
            if value is not None:
                return value
        if session is not None:
            value = getattr(session, field_name, None)
            if value is not None:
                return value
        return None

    @staticmethod
    def _snapshot_objective(
        *,
        existing,
        role: str,
        content: Any,
    ) -> str | None:
        if role == "user":
            return str(content)[:1024]
        return getattr(existing, "current_objective", None)

    async def _append_handoff_event(
        self,
        *,
        tenant_id: uuid.UUID,
        session: HumanHandoffSessionDE,
        actor_user_id: uuid.UUID | None,
        event_type: str,
        decision: str | None,
        reason: str | None,
        payload: dict[str, Any] | None,
        occurred_at: datetime | None = None,
    ) -> None:
        event_payload = self._handoff_event_payload(session=session, payload=payload)
        await self._event_service.create(
            {
                "tenant_id": tenant_id,
                "conversation_state_id": None,
                "channel_profile_id": None,
                "sender_key": self._normalize_optional_text(session.sender_id)
                or self._normalize_optional_text(session.room_id),
                "event_type": event_type,
                "decision": self._normalize_optional_text(decision),
                "reason": self._normalize_optional_text(reason),
                "payload": event_payload,
                "actor_user_id": actor_user_id,
                "occurred_at": occurred_at or self._now_utc(),
                "source": "human_handoff",
            }
        )

    @staticmethod
    def _handoff_event_payload(
        *,
        session: HumanHandoffSessionDE,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        output = dict(payload or {})
        output.setdefault(
            "session_id",
            None if session.id is None else str(session.id),
        )
        output.setdefault("scope_key", session.scope_key)
        output.setdefault("platform", session.platform)
        output.setdefault("channel_id", session.channel_id)
        output.setdefault("room_id", session.room_id)
        output.setdefault("sender_id", session.sender_id)
        output.setdefault("conversation_id", session.conversation_id)
        output.setdefault(
            "client_profile_id",
            None
            if session.client_profile_id is None
            else str(session.client_profile_id),
        )
        output.setdefault("service_route_key", session.service_route_key)
        output.setdefault("status", session.status)
        output.setdefault(
            "last_transcript_sequence_no",
            session.last_transcript_sequence_no,
        )
        return output

    async def _deliver_human_reply(
        self,
        *,
        session: HumanHandoffSessionDE,
        content: str,
        metadata: dict[str, Any],
    ) -> tuple[str, str | None]:
        try:
            await self._deliver_human_reply_or_raise(
                session=session,
                content=content,
                metadata=metadata,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return "failed", self._delivery_error(exc)
        return "sent", None

    async def _deliver_human_reply_or_raise(
        self,
        *,
        session: HumanHandoffSessionDE,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        platform = str(session.platform or "").strip().lower()
        room_id = self._normalize_optional_text(session.room_id)
        sender_id = self._normalize_optional_text(session.sender_id)
        recipient = sender_id or room_id
        if platform == "web":
            conversation_id = self._normalize_optional_text(session.conversation_id)
            if conversation_id is None:
                raise RuntimeError("web handoff delivery requires conversation_id")
            web_client = di.container.web_client
            await web_client.append_human_reply(
                conversation_id=conversation_id,
                content=content,
                metadata=metadata,
            )
            return

        if platform == "matrix":
            if room_id is None:
                raise RuntimeError("matrix handoff delivery requires room_id")
            await di.container.matrix_client.send_ingress_responses(
                room_id,
                [{"type": "text", "content": content}],
            )
            return

        if recipient is None:
            raise RuntimeError(f"{platform} handoff delivery requires a recipient")

        with client_profile_scope(session.client_profile_id):
            if platform == "line":
                await di.container.line_client.send_text_message(
                    recipient=recipient,
                    text=content,
                )
                return
            if platform == "telegram":
                await di.container.telegram_client.send_text_message(
                    chat_id=room_id or recipient,
                    text=content,
                )
                return
            if platform == "signal":
                await di.container.signal_client.send_text_message(
                    recipient=room_id or recipient,
                    text=content,
                )
                return
            if platform == "wechat":
                await di.container.wechat_client.send_text_message(
                    recipient=recipient,
                    text=content,
                )
                return
            if platform == "whatsapp":
                await di.container.whatsapp_client.send_text_message(
                    message=content,
                    recipient=recipient,
                )
                return

        raise RuntimeError(f"unsupported handoff delivery platform: {platform}")
