"""Unit tests for channel_orchestration HumanHandoffSessionService."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.context import ContextScope, ContextTurnRequest
from mugen.core.plugin.channel_orchestration.service import (
    human_handoff_session as handoff_module,
)
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
from mugen.core.plugin.channel_orchestration.service.human_handoff_release import (
    HumanHandoffReleaseHookRegistry,
)
from mugen.core.plugin.channel_orchestration.service.human_handoff_session import (
    HumanHandoffSessionService,
)
from mugen.core.utility.context_runtime import scope_key


def _service() -> HumanHandoffSessionService:
    service = HumanHandoffSessionService(
        table="channel_orchestration_human_handoff_session",
        rsg=Mock(),
    )
    service._now_utc = lambda: datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    return service


class TestMugenChannelOrchestrationHumanHandoffService(
    unittest.IsolatedAsyncioTestCase
):
    """Covers handoff action and context persistence behavior."""

    async def test_activate_handoff_builds_active_session_payload(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        session_id = uuid.uuid4()
        expected_scope = ContextScope(
            tenant_id=str(tenant_id),
            platform="matrix",
            channel_id="matrix",
            room_id="room-1",
            sender_id="user-1",
            conversation_id=None,
        )
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key=scope_key(expected_scope),
            status="active",
        )
        service._upsert_active_session = AsyncMock(return_value=session)
        service._append_handoff_event = AsyncMock()

        result, status = await service.action_activate_handoff(
            tenant_id=tenant_id,
            where={"tenant_id": tenant_id},
            auth_user_id=actor_id,
            data=ActivateHandoffValidation.model_validate(
                {
                    "Platform": " matrix ",
                    "ChannelId": "matrix",
                    "RoomId": "room-1",
                    "SenderId": "user-1",
                    "Reason": " need a person ",
                    "Metadata": {"priority": "high"},
                }
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["Decision"], "active")
        self.assertEqual(result["HumanHandoffSessionId"], str(session_id))
        self.assertEqual(result["ScopeKey"], scope_key(expected_scope))
        payload = service._upsert_active_session.await_args.kwargs["payload"]
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["owner_user_id"], actor_id)
        self.assertEqual(payload["reason"], "need a person")
        self.assertEqual(payload["attributes"], {"priority": "high"})
        self.assertIsNone(payload["conversation_id"])

    async def test_upsert_active_session_updates_existing_active_session(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        active = HumanHandoffSessionDE(id=session_id, tenant_id=tenant_id)
        updated = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            status="active",
        )
        service._active_session = AsyncMock(return_value=active)
        service.update = AsyncMock(return_value=updated)
        service.create = AsyncMock()

        result = await service._upsert_active_session(
            payload={
                "tenant_id": tenant_id,
                "scope_key": "scope-1",
                "status": "active",
            }
        )

        self.assertIs(result, updated)
        service.update.assert_awaited_once_with(
            {"tenant_id": tenant_id, "id": session_id},
            {
                "tenant_id": tenant_id,
                "scope_key": "scope-1",
                "status": "active",
            },
        )
        service.create.assert_not_called()

    async def test_deactivate_handoff_marks_session_inactive(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
            status="active",
        )
        service.get = AsyncMock(return_value=session)
        service.update = AsyncMock(return_value=session)
        service._append_handoff_event = AsyncMock()

        result, status = await service.action_deactivate_handoff(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=actor_id,
            data=DeactivateHandoffValidation.model_validate(
                {"Reason": "operator done"}
            ),
        )

        self.assertEqual((result, status), ({"Decision": "inactive"}, 200))
        changes = service.update.await_args.args[1]
        self.assertEqual(changes["status"], "inactive")
        self.assertEqual(changes["deactivated_by_user_id"], actor_id)
        self.assertEqual(changes["deactivation_reason"], "operator done")

    async def test_deactivate_handoff_invokes_matching_release_hook(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
            platform="whatsapp",
            channel_id="wa-channel",
            room_id="room-1",
            sender_id="sender-1",
            conversation_id="conversation-1",
            client_profile_id=profile_id,
            service_route_key="rentals",
            status="active",
        )
        service.get = AsyncMock(return_value=session)
        service.update = AsyncMock(return_value=session)
        service._append_handoff_event = AsyncMock()
        handler = SimpleNamespace(on_handoff_released=AsyncMock())
        registry = HumanHandoffReleaseHookRegistry()
        registry.register_handler(handler, service_route_key="rentals")

        with patch.object(
            handoff_module.di,
            "container",
            new=SimpleNamespace(
                get_ext_service=Mock(return_value=registry),
            ),
        ):
            result, status = await service.action_deactivate_handoff(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=actor_id,
                data=DeactivateHandoffValidation.model_validate(
                    {"Reason": "operator done"}
                ),
            )

        self.assertEqual((result, status), ({"Decision": "inactive"}, 200))
        handler.on_handoff_released.assert_awaited_once()
        release_event = handler.on_handoff_released.await_args.args[0]
        self.assertIsInstance(release_event, HumanHandoffReleased)
        self.assertEqual(release_event.tenant_id, tenant_id)
        self.assertEqual(release_event.actor_user_id, actor_id)
        self.assertEqual(release_event.reason, "operator done")
        self.assertEqual(
            release_event.deactivated_at,
            datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(release_event.session.status, "inactive")
        self.assertEqual(release_event.session.deactivated_by_user_id, actor_id)
        self.assertEqual(release_event.session.deactivation_reason, "operator done")
        self.assertEqual(release_event.session.platform, "whatsapp")
        self.assertEqual(release_event.session.client_profile_id, profile_id)
        self.assertEqual(release_event.session.service_route_key, "rentals")

        deactivate_event = service._append_handoff_event.await_args_list[0].kwargs
        hook_event = service._append_handoff_event.await_args_list[1].kwargs
        self.assertEqual(deactivate_event["event_type"], "deactivate_handoff")
        self.assertEqual(hook_event["event_type"], "handoff_release_hook")
        self.assertEqual(hook_event["decision"], "sent")
        self.assertIsNone(hook_event["reason"])
        self.assertEqual(
            hook_event["payload"],
            {
                "platform": "whatsapp",
                "channel_id": "wa-channel",
                "room_id": "room-1",
                "sender_id": "sender-1",
                "conversation_id": "conversation-1",
                "client_profile_id": str(profile_id),
                "service_route_key": "rentals",
            },
        )

    async def test_deactivate_handoff_records_not_configured_when_hook_missing(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
            status="active",
        )
        service.get = AsyncMock(return_value=session)
        service.update = AsyncMock(return_value=None)
        service._append_handoff_event = AsyncMock()

        with patch.object(
            handoff_module.di,
            "container",
            new=SimpleNamespace(get_ext_service=Mock(return_value=None)),
        ):
            result, status = await service.action_deactivate_handoff(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=DeactivateHandoffValidation(),
            )

        self.assertEqual((result, status), ({"Decision": "inactive"}, 200))
        hook_event = service._append_handoff_event.await_args_list[1].kwargs
        self.assertEqual(hook_event["event_type"], "handoff_release_hook")
        self.assertEqual(hook_event["decision"], "not_configured")
        self.assertIsNone(hook_event["reason"])
        self.assertIsNone(hook_event["payload"]["client_profile_id"])

    async def test_deactivate_handoff_records_skipped_for_empty_hook_registry(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
            service_route_key="unmatched",
            status="active",
        )
        service.get = AsyncMock(return_value=session)
        service.update = AsyncMock(return_value=session)
        service._append_handoff_event = AsyncMock()

        with patch.object(
            handoff_module.di,
            "container",
            new=SimpleNamespace(
                get_ext_service=Mock(return_value=HumanHandoffReleaseHookRegistry()),
            ),
        ):
            result, status = await service.action_deactivate_handoff(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=uuid.uuid4(),
                data=DeactivateHandoffValidation(),
            )

        self.assertEqual((result, status), ({"Decision": "inactive"}, 200))
        hook_event = service._append_handoff_event.await_args_list[1].kwargs
        self.assertEqual(hook_event["decision"], "skipped")
        self.assertIsNone(hook_event["reason"])

    async def test_deactivate_handoff_records_failed_hook_without_failing_release(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
            service_route_key="rentals",
            status="active",
        )
        service.get = AsyncMock(return_value=session)
        service.update = AsyncMock(return_value=None)
        service._append_handoff_event = AsyncMock()
        handler = SimpleNamespace(
            on_handoff_released=AsyncMock(side_effect=RuntimeError("hook down"))
        )
        registry = HumanHandoffReleaseHookRegistry()
        registry.register_handler(handler, service_route_key="rentals")

        with patch.object(
            handoff_module.di,
            "container",
            new=SimpleNamespace(get_ext_service=Mock(return_value=registry)),
        ):
            result, status = await service.action_deactivate_handoff(
                tenant_id=tenant_id,
                entity_id=session_id,
                where={"tenant_id": tenant_id, "id": session_id},
                auth_user_id=actor_id,
                data=DeactivateHandoffValidation.model_validate(
                    {"Reason": "done"}
                ),
            )

        self.assertEqual((result, status), ({"Decision": "inactive"}, 200))
        update_changes = service.update.await_args.args[1]
        self.assertEqual(update_changes["status"], "inactive")
        handler.on_handoff_released.assert_awaited_once()
        hook_event = service._append_handoff_event.await_args_list[1].kwargs
        self.assertEqual(hook_event["decision"], "failed")
        self.assertIn("RuntimeError: hook down", hook_event["reason"])

    async def test_notify_release_hook_defaults_blank_decision_to_sent(self) -> None:
        service = _service()
        registry = SimpleNamespace(notify_release=AsyncMock(return_value=" "))

        with patch.object(
            handoff_module.di,
            "container",
            new=SimpleNamespace(get_ext_service=Mock(return_value=registry)),
        ):
            decision, reason = await service._notify_release_hook(
                tenant_id=uuid.uuid4(),
                session=HumanHandoffSessionDE(status="inactive"),
                actor_user_id=None,
                reason=None,
                deactivated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual((decision, reason), ("sent", None))

    async def test_handoff_release_registry_selects_route_before_fallback(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        event = HumanHandoffReleased(
            tenant_id=tenant_id,
            session=HumanHandoffSessionDE(
                tenant_id=tenant_id,
                platform="WhatsApp",
                client_profile_id=profile_id,
                service_route_key="rentals",
            ),
            actor_user_id=uuid.uuid4(),
            reason="done",
            deactivated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        wrong_profile = SimpleNamespace(on_handoff_released=AsyncMock())
        route_handler = SimpleNamespace(on_handoff_released=AsyncMock())
        fallback_handler = SimpleNamespace(on_handoff_released=AsyncMock())
        registry = HumanHandoffReleaseHookRegistry()
        registry.register_handler(
            wrong_profile,
            service_route_key="rentals",
            client_profile_id=uuid.uuid4(),
        )
        registry.register_handler(
            fallback_handler,
            platform="whatsapp",
            client_profile_id=str(profile_id),
        )
        registry.register_handler(route_handler, service_route_key="rentals")

        self.assertIs(registry.select_handler(event), route_handler)
        self.assertEqual(await registry.notify_release(event), "sent")
        route_handler.on_handoff_released.assert_awaited_once_with(event)
        fallback_handler.on_handoff_released.assert_not_called()
        wrong_profile.on_handoff_released.assert_not_called()

    async def test_handoff_release_registry_uses_specific_fallback_handler(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        event = HumanHandoffReleased(
            tenant_id=tenant_id,
            session=HumanHandoffSessionDE(
                tenant_id=tenant_id,
                platform="telegram",
                client_profile_id=profile_id,
                service_route_key="missing-route",
            ),
            actor_user_id=None,
            reason=None,
            deactivated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        global_handler = SimpleNamespace(on_handoff_released=AsyncMock())
        platform_handler = SimpleNamespace(on_handoff_released=AsyncMock())
        profile_handler = SimpleNamespace(on_handoff_released=AsyncMock())
        wrong_platform = SimpleNamespace(on_handoff_released=AsyncMock())
        registry = HumanHandoffReleaseHookRegistry()
        registry.register_handler(global_handler)
        registry.register_handler(platform_handler, platform="telegram")
        registry.register_handler(profile_handler, client_profile_id=profile_id)
        registry.register_handler(wrong_platform, platform="signal")

        self.assertIs(registry.select_handler(event), platform_handler)
        self.assertEqual(await registry.notify_release(event), "sent")
        platform_handler.on_handoff_released.assert_awaited_once_with(event)
        global_handler.on_handoff_released.assert_not_called()
        profile_handler.on_handoff_released.assert_not_called()
        wrong_platform.on_handoff_released.assert_not_called()

    async def test_handoff_release_registry_skips_when_no_handler_matches(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        event = HumanHandoffReleased(
            tenant_id=tenant_id,
            session=HumanHandoffSessionDE(
                tenant_id=tenant_id,
                platform="signal",
                service_route_key=None,
            ),
            actor_user_id=None,
            reason=None,
            deactivated_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
        )
        registry = HumanHandoffReleaseHookRegistry()
        registry.register_handler(
            SimpleNamespace(on_handoff_released=AsyncMock()),
            platform="telegram",
        )

        self.assertIsNone(registry.select_handler(event))
        self.assertEqual(await registry.notify_release(event), "skipped")

    def test_handoff_release_registry_rejects_invalid_handler(self) -> None:
        registry = HumanHandoffReleaseHookRegistry()

        with self.assertRaisesRegex(
            TypeError,
            "handler must define on_handoff_released.",
        ):
            registry.register_handler(SimpleNamespace())

    async def test_stream_handoff_events_replays_after_last_event_id(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        cursor_id = uuid.uuid4()
        filtered_id = uuid.uuid4()
        no_timestamp_id = uuid.uuid4()
        next_id = uuid.uuid4()
        later_id = uuid.uuid4()
        cursor_event = OrchestrationEventDE(
            id=cursor_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 41,
            },
            occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            source="human_handoff",
        )
        filtered_event = OrchestrationEventDE(
            id=filtered_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(uuid.uuid4()),
                "status": "active",
                "sequence_no": 41,
            },
            occurred_at=datetime(2026, 6, 1, 12, 0, 30, tzinfo=timezone.utc),
            source="human_handoff",
        )
        no_timestamp_event = OrchestrationEventDE(
            id=no_timestamp_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 42,
            },
            occurred_at=None,
            source="human_handoff",
        )
        next_event = OrchestrationEventDE(
            id=next_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 43,
            },
            occurred_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
            source="human_handoff",
        )
        later_event = OrchestrationEventDE(
            id=later_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 44,
            },
            occurred_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
            source="human_handoff",
        )
        service._event_service.get = AsyncMock(return_value=cursor_event)
        service._event_service.list = AsyncMock(
            return_value=[
                cursor_event,
                filtered_event,
                no_timestamp_event,
                next_event,
                later_event,
            ]
        )

        stream = await service.stream_handoff_events(
            tenant_id=tenant_id,
            last_event_id=f"{tenant_id}:{cursor_id}",
            session_id=session_id,
            status="active",
        )
        try:
            chunk = await anext(stream)
            next_chunk = await anext(stream)
            later_chunk = await anext(stream)
        finally:
            await stream.aclose()

        self.assertIn(f"id: {tenant_id}:{no_timestamp_id}", chunk)
        self.assertIn("event: handoff.transcript_appended", chunk)
        self.assertIn(f'"session_id":"{session_id}"', chunk)
        self.assertIn('"sequence_no":42', chunk)
        self.assertIn(f"id: {tenant_id}:{next_id}", next_chunk)
        self.assertIn('"sequence_no":43', next_chunk)
        self.assertIn(f"id: {tenant_id}:{later_id}", later_chunk)
        self.assertIn('"sequence_no":44', later_chunk)

    async def test_stream_handoff_events_sends_reset_for_bad_cursor(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        service._event_service.list = AsyncMock(return_value=[])

        stream = await service.stream_handoff_events(
            tenant_id=tenant_id,
            last_event_id="bad-cursor",
        )
        try:
            chunk = await anext(stream)
        finally:
            await stream.aclose()

        self.assertIn("event: handoff.stream_reset", chunk)
        self.assertIn('"reason":"cursor_unavailable"', chunk)

    def test_stream_payload_maps_delivery_and_filters_session(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        event = OrchestrationEventDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_type="human_reply",
            decision="failed",
            reason="Provider rejected message",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "delivery_status": "failed",
                "delivery_error": "Provider rejected message",
            },
            occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            source="human_handoff",
        )

        payload = HumanHandoffSessionService._stream_payload_for_event(
            tenant_id=tenant_id,
            event=event,
            session_id_filter=str(session_id),
            status_filter="active",
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["event_type"], "handoff.reply_failed")
        self.assertEqual(payload["delivery_status"], "failed")
        self.assertEqual(payload["delivery_error"], "Provider rejected message")
        self.assertIsNone(
            HumanHandoffSessionService._stream_payload_for_event(
                tenant_id=tenant_id,
                event=event,
                session_id_filter=str(uuid.uuid4()),
                status_filter="active",
            )
        )
        self.assertIsNone(
            HumanHandoffSessionService._stream_payload_for_event(
                tenant_id=tenant_id,
                event=event,
                session_id_filter=str(session_id),
                status_filter="inactive",
            )
        )

    async def test_stream_handoff_events_polls_live_rows_and_keepalive(
        self,
    ) -> None:
        service = _service()
        service._STREAM_KEEPALIVE_SECONDS = 0.0
        service._STREAM_POLL_SECONDS = 0.0
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        third_id = uuid.uuid4()
        no_id_filtered_event = OrchestrationEventDE(
            id=None,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "inactive",
                "sequence_no": 0,
            },
            occurred_at=None,
            source="human_handoff",
        )
        first_event = OrchestrationEventDE(
            id=first_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 1,
            },
            occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            source="human_handoff",
        )
        filtered_event = OrchestrationEventDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "inactive",
                "sequence_no": 2,
            },
            occurred_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
            source="human_handoff",
        )
        second_event = OrchestrationEventDE(
            id=second_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 3,
            },
            occurred_at=datetime(2026, 6, 1, 12, 2, tzinfo=timezone.utc),
            source="human_handoff",
        )
        third_event = OrchestrationEventDE(
            id=third_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 4,
            },
            occurred_at=datetime(2026, 6, 1, 12, 3, tzinfo=timezone.utc),
            source="human_handoff",
        )
        service._event_service.list = AsyncMock(
            side_effect=[
                [],
                [no_id_filtered_event, first_event],
                [first_event, filtered_event, second_event],
                [],
                [third_event],
            ]
        )

        stream = await service.stream_handoff_events(
            tenant_id=tenant_id,
            status="active",
        )
        try:
            first_chunk = await anext(stream)
            second_chunk = await anext(stream)
            ping_chunk = await anext(stream)
            third_chunk = await anext(stream)
        finally:
            await stream.aclose()

        self.assertIn(f"id: {tenant_id}:{first_id}", first_chunk)
        self.assertIn('"sequence_no":1', first_chunk)
        self.assertIn(f"id: {tenant_id}:{second_id}", second_chunk)
        self.assertIn('"sequence_no":3', second_chunk)
        self.assertEqual(ping_chunk, ": ping\n\n")
        self.assertIn(f"id: {tenant_id}:{third_id}", third_chunk)
        self.assertIn('"sequence_no":4', third_chunk)

    async def test_stream_handoff_events_waits_before_keepalive_when_not_due(
        self,
    ) -> None:
        service = _service()
        service._STREAM_KEEPALIVE_SECONDS = 60.0
        service._STREAM_POLL_SECONDS = 0.0
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        event_id = uuid.uuid4()
        event = OrchestrationEventDE(
            id=event_id,
            tenant_id=tenant_id,
            event_type="handoff.transcript_appended",
            payload={
                "session_id": str(session_id),
                "status": "active",
                "sequence_no": 1,
            },
            occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            source="human_handoff",
        )
        service._event_service.list = AsyncMock(
            side_effect=[
                [],
                [],
                [event],
            ]
        )

        stream = await service.stream_handoff_events(tenant_id=tenant_id)
        try:
            chunk = await anext(stream)
        finally:
            await stream.aclose()

        self.assertIn(f"id: {tenant_id}:{event_id}", chunk)
        self.assertIn("event: handoff.transcript_appended", chunk)

    async def test_stream_cursor_helpers_cover_edge_cases(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        other_tenant_id = uuid.uuid4()
        missing_id = uuid.uuid4()

        cursor_event, reset_reason = await service._resolve_stream_cursor(
            tenant_id=tenant_id,
            last_event_id=None,
        )
        self.assertIsNone(cursor_event)
        self.assertIsNone(reset_reason)

        service._event_service.get = AsyncMock(return_value=None)
        cursor_event, reset_reason = await service._resolve_stream_cursor(
            tenant_id=tenant_id,
            last_event_id=str(missing_id),
        )
        self.assertIsNone(cursor_event)
        self.assertEqual(reset_reason, "cursor_unavailable")
        self.assertIsNone(
            HumanHandoffSessionService._parse_stream_event_id(
                tenant_id=tenant_id,
                event_id=f"{other_tenant_id}:{missing_id}",
            )
        )
        self.assertIsNone(
            HumanHandoffSessionService._stream_event_id(
                tenant_id=tenant_id,
                event=OrchestrationEventDE(id=None),
            )
        )

        self.assertEqual(
            await service._stream_events_since(
                tenant_id=tenant_id,
                cursor_event=OrchestrationEventDE(id=missing_id),
            ),
            [],
        )
        service._stream_events_after_timestamp = AsyncMock(
            return_value=[
                OrchestrationEventDE(
                    id=uuid.uuid4(),
                    occurred_at=datetime(
                        2026,
                        6,
                        1,
                        12,
                        1,
                        tzinfo=timezone.utc,
                    ),
                )
            ]
        )
        self.assertEqual(
            await service._stream_events_since(
                tenant_id=tenant_id,
                cursor_event=OrchestrationEventDE(
                    id=missing_id,
                    occurred_at=datetime(
                        2026,
                        6,
                        1,
                        12,
                        0,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
            [],
        )

    async def test_update_transcript_markers_handles_missing_session_id(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        service.update = AsyncMock()

        self.assertIsNone(
            await service._update_transcript_markers(
                tenant_id=tenant_id,
                session=HumanHandoffSessionDE(id=None),
                sequence_no=2,
            )
        )

        session = HumanHandoffSessionDE(id=uuid.uuid4(), tenant_id=tenant_id)
        updated = HumanHandoffSessionDE(id=session.id, tenant_id=tenant_id)
        service.update = AsyncMock(return_value=updated)

        self.assertIs(
            await service._update_transcript_markers(
                tenant_id=tenant_id,
                session=session,
                sequence_no=3,
            ),
            updated,
        )
        self.assertEqual(
            service.update.await_args.args[1],
            {"last_transcript_sequence_no": 3},
        )

    def test_stream_payload_ignores_invalid_or_unknown_events(self) -> None:
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()

        self.assertIsNone(
            HumanHandoffSessionService._stream_payload_for_event(
                tenant_id=tenant_id,
                event=OrchestrationEventDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    event_type="handoff.transcript_appended",
                    payload={},
                ),
                session_id_filter=None,
                status_filter=None,
            )
        )
        self.assertIsNone(
            HumanHandoffSessionService._stream_payload_for_event(
                tenant_id=tenant_id,
                event=OrchestrationEventDE(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    event_type="unknown",
                    payload={"session_id": str(session_id)},
                ),
                session_id_filter=None,
                status_filter=None,
            )
        )

    def test_public_stream_event_type_mappings(self) -> None:
        cases = [
            ("activate_handoff", None, "handoff.session_activated"),
            ("deactivate_handoff", None, "handoff.session_released"),
            ("handoff_release_hook", None, "handoff.session_updated"),
            ("human_reply", "sent", "handoff.reply_delivered"),
            ("human_reply", "failed", "handoff.reply_failed"),
        ]

        for event_type, decision, expected in cases:
            with self.subTest(event_type=event_type, decision=decision):
                self.assertEqual(
                    HumanHandoffSessionService._public_stream_event_type(
                        event=OrchestrationEventDE(
                            event_type=event_type,
                            decision=decision,
                        ),
                        payload={},
                    ),
                    expected,
                )
        self.assertIsNone(
            HumanHandoffSessionService._public_stream_event_type(
                event=OrchestrationEventDE(
                    event_type="human_reply",
                    decision="queued",
                ),
                payload={},
            )
        )

    async def test_append_user_turn_skips_marker_update_without_session(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        scope = ContextScope(
            tenant_id=str(tenant_id),
            platform="matrix",
            room_id="room-1",
            sender_id="sender-1",
        )
        request = ContextTurnRequest(
            scope=scope,
            user_message="hello during handoff",
        )
        service.active_session_for_request = AsyncMock(return_value=None)
        service._append_context_event = AsyncMock(return_value=9)
        service.update = AsyncMock()
        service._append_handoff_event = AsyncMock()

        await service.append_user_turn(request)

        service._append_context_event.assert_awaited_once()
        service.update.assert_not_awaited()
        service._append_handoff_event.assert_not_awaited()

    async def test_append_context_event_advances_snapshot_revision(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        snapshot_id = uuid.uuid4()
        scope = ContextScope(
            tenant_id=str(tenant_id),
            platform="matrix",
            channel_id="matrix",
            room_id="room-1",
            sender_id="user-1",
        )
        service._context_event_service.list = AsyncMock(
            return_value=[SimpleNamespace(sequence_no=10)]
        )
        service._context_event_service.create = AsyncMock()
        service._context_snapshot_service.get = AsyncMock(
            return_value=SimpleNamespace(
                id=snapshot_id,
                row_version=3,
                revision=5,
                attributes={"existing": True},
                entities={},
                constraints=[],
                unresolved_slots=[],
                commitments=[],
                safety_flags=[],
                routing={},
            )
        )
        service._context_snapshot_service.update_with_row_version = AsyncMock(
            return_value=SimpleNamespace(id=snapshot_id)
        )

        await service._append_context_event(
            tenant_id=tenant_id,
            scope_key_value=scope_key(scope),
            role="user",
            content="hello during handoff",
            message_id="msg-1",
            trace_id="trace-1",
            source="human_handoff_user_turn",
            scope=scope,
        )

        event_payload = service._context_event_service.create.await_args.args[0]
        self.assertEqual(event_payload["sequence_no"], 11)
        self.assertEqual(event_payload["role"], "user")
        snapshot_changes = (
            service._context_snapshot_service.update_with_row_version.await_args
            .kwargs["changes"]
        )
        self.assertEqual(snapshot_changes["revision"], 6)
        self.assertEqual(snapshot_changes["current_objective"], "hello during handoff")
        self.assertEqual(
            snapshot_changes["attributes"]["human_handoff"]["last_sequence_no"],
            11,
        )

    async def test_human_reply_records_failed_delivery_status_once(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
            platform="matrix",
            room_id="room-1",
            sender_id="user-1",
            status="active",
        )
        service.get = AsyncMock(return_value=session)
        service._append_context_event = AsyncMock(return_value=7)
        service._deliver_human_reply = AsyncMock(return_value=("failed", "boom"))
        service.update = AsyncMock(return_value=session)
        service._append_handoff_event = AsyncMock()

        result, status = await service.action_human_reply(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=actor_id,
            data=HumanReplyValidation.model_validate(
                {
                    "Content": "Human answer",
                    "MessageId": "reply-1",
                    "TraceId": "trace-1",
                }
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["DeliveryStatus"], "failed")
        service._append_context_event.assert_awaited_once()
        append_kwargs = service._append_context_event.await_args.kwargs
        self.assertEqual(append_kwargs["role"], "assistant")
        self.assertEqual(append_kwargs["source"], "human_handoff")
        update_changes = service.update.await_args.args[1]
        self.assertEqual(update_changes["last_human_reply_at"], service._now_utc())
        self.assertEqual(update_changes["last_transcript_sequence_no"], 7)
        self.assertEqual(update_changes["last_delivery_status"], "failed")
        self.assertEqual(update_changes["last_delivery_error"], "boom")
        self.assertEqual(service._append_handoff_event.await_count, 2)
        transcript_event = service._append_handoff_event.await_args_list[0].kwargs
        delivery_event = service._append_handoff_event.await_args_list[1].kwargs
        self.assertEqual(
            transcript_event["event_type"],
            "handoff.transcript_appended",
        )
        self.assertEqual(transcript_event["payload"]["sequence_no"], 7)
        self.assertEqual(delivery_event["event_type"], "human_reply")
        self.assertEqual(delivery_event["payload"]["delivery_status"], "failed")
        self.assertEqual(delivery_event["payload"]["delivery_error"], "boom")

    async def test_list_transcript_returns_chronological_recent_rows(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
        )
        service.get = AsyncMock(return_value=session)
        service._context_event_service.list = AsyncMock(
            return_value=[
                SimpleNamespace(
                    sequence_no=2,
                    role="assistant",
                    content="hello",
                    message_id="m2",
                    trace_id="t2",
                    source="human_handoff",
                    occurred_at=datetime(2026, 6, 1, 12, 1, tzinfo=timezone.utc),
                ),
                SimpleNamespace(
                    sequence_no=1,
                    role="user",
                    content="hi",
                    message_id="m1",
                    trace_id="t1",
                    source="human_handoff_user_turn",
                    occurred_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
                ),
            ]
        )

        result, status = await service.action_list_transcript(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=uuid.uuid4(),
            data=ListTranscriptValidation.model_validate({"Limit": 20}),
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["Count"], 2)
        self.assertEqual([item["SequenceNo"] for item in result["Items"]], [1, 2])
        self.assertEqual(result["LatestSequenceNo"], 2)
        self.assertFalse(result["HasMore"])

    async def test_list_transcript_supports_after_sequence_no(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=session_id,
            tenant_id=tenant_id,
            scope_key="scope-1",
        )
        service.get = AsyncMock(return_value=session)
        service._context_event_service.list = AsyncMock(
            side_effect=[
                [
                    SimpleNamespace(
                        sequence_no=42,
                        role="user",
                        content="new",
                        message_id="m42",
                        trace_id="t42",
                        source="human_handoff_user_turn",
                        occurred_at=datetime(
                            2026,
                            6,
                            1,
                            12,
                            2,
                            tzinfo=timezone.utc,
                        ),
                    ),
                    SimpleNamespace(
                        sequence_no=43,
                        role="assistant",
                        content="newer",
                        message_id="m43",
                        trace_id="t43",
                        source="human_handoff",
                        occurred_at=datetime(
                            2026,
                            6,
                            1,
                            12,
                            3,
                            tzinfo=timezone.utc,
                        ),
                    ),
                ],
                [SimpleNamespace(sequence_no=43)],
            ]
        )

        result, status = await service.action_list_transcript(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=uuid.uuid4(),
            data=ListTranscriptValidation.model_validate(
                {
                    "Limit": 1,
                    "AfterSequenceNo": 41,
                }
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(result["Count"], 1)
        self.assertEqual([item["SequenceNo"] for item in result["Items"]], [42])
        self.assertEqual(result["LatestSequenceNo"], 43)
        self.assertTrue(result["HasMore"])
        list_kwargs = service._context_event_service.list.await_args_list[0].kwargs
        scalar_filter = list_kwargs["filter_groups"][0].scalar_filters[0]
        self.assertEqual(scalar_filter.field, "sequence_no")
        self.assertEqual(scalar_filter.value, 41)

    def test_helper_normalization_and_request_metadata_resolution(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        request = ContextTurnRequest(
            scope=ContextScope(
                tenant_id=str(tenant_id),
                platform="matrix",
                room_id="room-1",
                sender_id="sender-1",
            ),
            user_message="hello",
            ingress_metadata={
                "ingress_route": {
                    "client_profile_id": str(profile_id),
                    "service_route_key": " support ",
                },
                "client_profile_id": "ignored",
                "service_route_key": "fallback",
            },
        )

        self.assertIsInstance(HumanHandoffSessionService._now_utc(), datetime)
        self.assertIsNone(service._normalize_optional_text(None))
        self.assertIsNone(service._normalize_optional_text("   "))
        self.assertEqual(service._normalize_optional_text(123), "123")
        self.assertIn(
            "RuntimeError",
            service._delivery_error(RuntimeError("delivery failed")),
        )
        self.assertEqual(service._request_client_profile_id(request), profile_id)
        self.assertEqual(service._request_service_route_key(request), "support")

        fallback_request = ContextTurnRequest(
            scope=request.scope,
            user_message="hello",
            ingress_metadata={
                "ingress_route": {"client_profile_id": "", "service_route_key": " "},
                "client_profile_id": "not-a-uuid",
                "service_route_key": "fallback",
            },
        )
        self.assertIsNone(service._request_client_profile_id(fallback_request))
        self.assertEqual(
            service._request_service_route_key(fallback_request),
            "fallback",
        )

        empty_request = ContextTurnRequest(
            scope=request.scope,
            user_message="hello",
            ingress_metadata={"ingress_route": object()},
        )
        self.assertIsNone(service._request_client_profile_id(empty_request))
        self.assertIsNone(service._request_service_route_key(empty_request))

    async def test_active_session_for_request_handles_valid_and_invalid_tenant(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        scope = ContextScope(
            tenant_id=str(tenant_id),
            platform="matrix",
            room_id="room-1",
            sender_id="sender-1",
        )
        active = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key=scope_key(scope),
            status="active",
        )
        service._active_session = AsyncMock(return_value=active)

        result = await service.active_session_for_request(
            ContextTurnRequest(scope=scope, user_message="hello")
        )

        self.assertIs(result, active)
        service._active_session.assert_awaited_once_with(
            tenant_id=tenant_id,
            scope_key_value=scope_key(scope),
        )

        invalid = await service.active_session_for_request(
            ContextTurnRequest(
                scope=ContextScope(
                    tenant_id="not-a-uuid",
                    platform="matrix",
                    room_id="room-1",
                    sender_id="sender-1",
                ),
                user_message="hello",
            )
        )
        self.assertIsNone(invalid)

    async def test_activate_for_turn_persists_assistant_requested_session(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        request = ContextTurnRequest(
            scope=ContextScope(
                tenant_id=str(tenant_id),
                platform="web",
                channel_id="web",
                room_id="room-1",
                sender_id="sender-1",
                conversation_id="conversation-1",
            ),
            user_message="help me",
            ingress_metadata={
                "ingress_route": {
                    "client_profile_id": str(profile_id),
                    "service_route_key": " concierge ",
                },
            },
        )
        session = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key=scope_key(request.scope),
            status="active",
        )
        service._upsert_active_session = AsyncMock(return_value=session)
        service._append_handoff_event = AsyncMock()

        result = await service.activate_for_turn(
            request,
            reason="agent requested help",
            owner_user_id=actor_id,
            metadata={"trigger": "agent"},
        )

        self.assertIs(result, session)
        payload = service._upsert_active_session.await_args.kwargs["payload"]
        self.assertEqual(payload["tenant_id"], tenant_id)
        self.assertEqual(payload["scope_key"], scope_key(request.scope))
        self.assertEqual(payload["client_profile_id"], profile_id)
        self.assertEqual(payload["service_route_key"], "concierge")
        self.assertEqual(payload["owner_user_id"], actor_id)
        self.assertEqual(payload["attributes"], {"trigger": "agent"})
        event_kwargs = service._append_handoff_event.await_args.kwargs
        self.assertEqual(event_kwargs["payload"], {"source": "assistant"})

    async def test_append_user_turn_writes_user_context_event(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        scope = ContextScope(
            tenant_id=str(tenant_id),
            platform="matrix",
            room_id="room-1",
            sender_id="sender-1",
        )
        request = ContextTurnRequest(
            scope=scope,
            user_message="hello during handoff",
            message_id="msg-1",
            trace_id="trace-1",
        )
        session = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key=scope_key(scope),
            status="active",
        )
        service.active_session_for_request = AsyncMock(return_value=session)
        service._append_context_event = AsyncMock(return_value=9)
        service.update = AsyncMock(
            return_value=HumanHandoffSessionDE(
                id=session.id,
                tenant_id=tenant_id,
                scope_key=scope_key(scope),
                status="active",
                last_user_message_at=service._now_utc(),
                last_transcript_sequence_no=9,
            )
        )
        service._append_handoff_event = AsyncMock()

        await service.append_user_turn(request)

        append_kwargs = service._append_context_event.await_args.kwargs
        self.assertEqual(append_kwargs["tenant_id"], tenant_id)
        self.assertEqual(append_kwargs["scope_key_value"], scope_key(scope))
        self.assertEqual(append_kwargs["role"], "user")
        self.assertEqual(append_kwargs["content"], "hello during handoff")
        self.assertEqual(append_kwargs["message_id"], "msg-1")
        self.assertEqual(append_kwargs["trace_id"], "trace-1")
        self.assertEqual(append_kwargs["source"], "human_handoff_user_turn")
        self.assertIs(append_kwargs["scope"], scope)
        self.assertIs(append_kwargs["session"], session)
        self.assertEqual(append_kwargs["occurred_at"], service._now_utc())
        update_changes = service.update.await_args.args[1]
        self.assertEqual(update_changes["last_user_message_at"], service._now_utc())
        self.assertEqual(update_changes["last_transcript_sequence_no"], 9)
        event_kwargs = service._append_handoff_event.await_args.kwargs
        self.assertEqual(event_kwargs["event_type"], "handoff.transcript_appended")
        self.assertEqual(event_kwargs["decision"], "user")
        self.assertEqual(event_kwargs["payload"]["sequence_no"], 9)

    async def test_deactivate_handoff_is_idempotent_when_already_inactive(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        service.get = AsyncMock(
            return_value=HumanHandoffSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                status="inactive",
            )
        )
        service.update = AsyncMock()
        service._append_handoff_event = AsyncMock()

        result, status = await service.action_deactivate_handoff(
            tenant_id=tenant_id,
            entity_id=session_id,
            where={"tenant_id": tenant_id, "id": session_id},
            auth_user_id=uuid.uuid4(),
            data=DeactivateHandoffValidation(),
        )

        self.assertEqual((result, status), ({"Decision": "inactive"}, 200))
        service.update.assert_not_called()
        service._append_handoff_event.assert_not_called()

    async def test_human_reply_rejects_inactive_session(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session_id = uuid.uuid4()
        service.get = AsyncMock(
            return_value=HumanHandoffSessionDE(
                id=session_id,
                tenant_id=tenant_id,
                status="inactive",
            )
        )

        with patch.object(
            handoff_module,
            "abort",
            side_effect=RuntimeError("inactive handoff"),
        ) as abort_mock:
            with self.assertRaisesRegex(RuntimeError, "inactive handoff"):
                await service.action_human_reply(
                    tenant_id=tenant_id,
                    entity_id=session_id,
                    where={"tenant_id": tenant_id, "id": session_id},
                    auth_user_id=uuid.uuid4(),
                    data=HumanReplyValidation(Content="hello"),
                )

        abort_mock.assert_called_once_with(
            409,
            "Human handoff session is not active.",
        )

    async def test_get_session_for_action_aborts_on_missing_or_storage_error(
        self,
    ) -> None:
        service = _service()

        service.get = AsyncMock(return_value=None)
        with patch.object(
            handoff_module,
            "abort",
            side_effect=RuntimeError("missing"),
        ) as abort_mock:
            with self.assertRaisesRegex(RuntimeError, "missing"):
                await service._get_session_for_action(where={"id": uuid.uuid4()})
        abort_mock.assert_called_once_with(404, "Human handoff session not found.")

        service.get = AsyncMock(side_effect=SQLAlchemyError("db down"))
        with patch.object(
            handoff_module,
            "abort",
            side_effect=RuntimeError("storage"),
        ) as abort_mock:
            with self.assertRaisesRegex(RuntimeError, "storage"):
                await service._get_session_for_action(where={"id": uuid.uuid4()})
        abort_mock.assert_called_once_with(500)

    async def test_active_session_lists_most_recent_active_session(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key="scope-1",
            status="active",
        )
        service.list = AsyncMock(return_value=[session])

        result = await service._active_session(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
        )

        self.assertIs(result, session)
        self.assertEqual(service.list.await_args.kwargs["limit"], 1)

        service.list = AsyncMock(return_value=[])
        result = await service._active_session(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
        )
        self.assertIsNone(result)

    async def test_upsert_active_session_reuses_inactive_row_or_creates(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        inactive = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key="scope-1",
            status="inactive",
        )
        service._active_session = AsyncMock(return_value=None)
        service.list = AsyncMock(return_value=[inactive])
        service.update = AsyncMock(return_value=None)
        service.create = AsyncMock()

        result = await service._upsert_active_session(
            payload={
                "tenant_id": tenant_id,
                "scope_key": "scope-1",
                "status": "active",
            }
        )

        self.assertIs(result, inactive)
        service.update.assert_awaited_once()
        service.create.assert_not_called()

        created = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key="scope-2",
            status="active",
        )
        service.list = AsyncMock(return_value=[])
        service.update = AsyncMock()
        service.create = AsyncMock(return_value=created)

        result = await service._upsert_active_session(
            payload={
                "tenant_id": tenant_id,
                "scope_key": "scope-2",
                "status": "active",
            }
        )

        self.assertIs(result, created)
        service.update.assert_not_called()

    async def test_upsert_active_session_falls_back_to_existing_active_row(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        active = HumanHandoffSessionDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope_key="scope-1",
            status="active",
        )
        service._active_session = AsyncMock(return_value=active)
        service.update = AsyncMock(return_value=None)

        result = await service._upsert_active_session(
            payload={
                "tenant_id": tenant_id,
                "scope_key": "scope-1",
                "status": "active",
            }
        )

        self.assertIs(result, active)

    async def test_append_context_event_starts_at_one_and_retries_integrity(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        service._context_event_service.list = AsyncMock(
            side_effect=[
                [],
                [SimpleNamespace(sequence_no=1)],
            ]
        )
        service._context_event_service.create = AsyncMock(
            side_effect=[
                IntegrityError("insert", {}, Exception("dupe")),
                None,
            ]
        )
        service._advance_context_snapshot = AsyncMock()

        await service._append_context_event(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
            role="assistant",
            content="hello",
            message_id=" ",
            trace_id=None,
            source="human_handoff",
        )

        self.assertEqual(service._context_event_service.create.await_count, 2)
        first_payload = service._context_event_service.create.await_args_list[0].args[0]
        second_payload = (
            service._context_event_service.create.await_args_list[1].args[0]
        )
        self.assertEqual(first_payload["sequence_no"], 1)
        self.assertEqual(second_payload["sequence_no"], 2)
        self.assertIsNone(second_payload["message_id"])
        service._advance_context_snapshot.assert_awaited_once()

    async def test_append_context_event_raises_after_sequence_conflicts(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        service._context_event_service.list = AsyncMock(return_value=[])
        service._context_event_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("dupe"))
        )
        service._advance_context_snapshot = AsyncMock()

        with self.assertRaisesRegex(
            RuntimeError,
            "Context event sequence allocation conflict.",
        ):
            await service._append_context_event(
                tenant_id=tenant_id,
                scope_key_value="scope-1",
                role="assistant",
                content="hello",
                message_id=None,
                trace_id=None,
                source="human_handoff",
            )

        self.assertEqual(
            service._context_event_service.create.await_count,
            service._EVENT_SEQUENCE_ATTEMPTS,
        )
        service._advance_context_snapshot.assert_not_called()

    async def test_advance_context_snapshot_create_and_retry_update_paths(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        service._context_snapshot_service.get = AsyncMock(return_value=None)
        service._context_snapshot_service.create = AsyncMock()

        await service._advance_context_snapshot(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
            sequence_no=1,
            role="user",
            content="objective",
            message_id="msg-1",
            trace_id="trace-1",
            source="human_handoff_user_turn",
            scope=None,
            session=None,
        )

        create_payload = service._context_snapshot_service.create.await_args.args[0]
        self.assertEqual(create_payload["revision"], 1)
        self.assertEqual(create_payload["current_objective"], "objective")

        existing = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=None,
            revision=0,
            current_objective="old objective",
            attributes={},
        )
        service._context_snapshot_service.get = AsyncMock(
            side_effect=[None, existing]
        )
        service._context_snapshot_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("dupe"))
        )
        service._context_snapshot_service.update = AsyncMock(
            return_value=SimpleNamespace(id=existing.id)
        )

        await service._advance_context_snapshot(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
            sequence_no=2,
            role="assistant",
            content="answer",
            message_id=None,
            trace_id=None,
            source="human_handoff",
            scope=None,
            session=None,
        )

        service._context_snapshot_service.update.assert_awaited_once()
        update_payload = service._context_snapshot_service.update.await_args.args[1]
        self.assertEqual(update_payload["current_objective"], "old objective")

    async def test_advance_context_snapshot_conflict_exhaustion_raises(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        existing = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=7,
            revision=3,
            current_objective="old objective",
            attributes={},
        )
        service._context_snapshot_service.get = AsyncMock(return_value=existing)
        service._context_snapshot_service.update_with_row_version = AsyncMock(
            return_value=None
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Context snapshot revision update conflict.",
        ):
            await service._advance_context_snapshot(
                tenant_id=tenant_id,
                scope_key_value="scope-1",
                sequence_no=4,
                role="assistant",
                content="answer",
                message_id=None,
                trace_id=None,
                source="human_handoff",
                scope=None,
                session=None,
            )

        self.assertEqual(
            service._context_snapshot_service.update_with_row_version.await_count,
            service._SNAPSHOT_UPDATE_ATTEMPTS,
        )

    async def test_advance_context_snapshot_creates_when_existing_has_no_id(
        self,
    ) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        existing_without_id = SimpleNamespace(
            id=None,
            revision=0,
            attributes={},
        )
        service._context_snapshot_service.get = AsyncMock(
            return_value=existing_without_id
        )
        service._context_snapshot_service.create = AsyncMock()

        await service._advance_context_snapshot(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
            sequence_no=1,
            role="assistant",
            content="answer",
            message_id=None,
            trace_id=None,
            source="human_handoff",
            scope=None,
            session=None,
        )

        service._context_snapshot_service.create.assert_awaited_once()

    def test_context_snapshot_payload_scope_and_objective_fallbacks(self) -> None:
        tenant_id = uuid.uuid4()
        existing = SimpleNamespace(
            revision=9,
            platform="existing-platform",
            current_objective="existing objective",
            entities={"e": "v"},
            constraints=["c"],
            unresolved_slots=["slot"],
            commitments=["commitment"],
            safety_flags=["safe"],
            routing={"route": "default"},
            summary="summary",
            attributes={"existing": True},
            case_id="case-1",
            workflow_id="workflow-1",
        )
        session = HumanHandoffSessionDE(
            platform="session-platform",
            channel_id="session-channel",
            room_id="session-room",
            sender_id="session-sender",
            conversation_id="session-conversation",
        )

        payload = HumanHandoffSessionService._context_snapshot_payload(
            tenant_id=tenant_id,
            scope_key_value="scope-1",
            existing=existing,
            next_revision=3,
            sequence_no=6,
            role="assistant",
            content="answer",
            message_id=" message ",
            trace_id=" trace ",
            source="human_handoff",
            scope=None,
            session=session,
        )

        self.assertEqual(payload["revision"], 9)
        self.assertEqual(payload["platform"], "existing-platform")
        self.assertEqual(payload["channel_id"], "session-channel")
        self.assertEqual(payload["current_objective"], "existing objective")
        self.assertEqual(payload["last_message_id"], "message")
        self.assertEqual(payload["last_trace_id"], "trace")
        self.assertEqual(payload["entities"], {"e": "v"})
        self.assertEqual(payload["constraints"], ["c"])
        self.assertEqual(payload["unresolved_slots"], ["slot"])
        self.assertEqual(payload["commitments"], ["commitment"])
        self.assertEqual(payload["safety_flags"], ["safe"])
        self.assertEqual(payload["routing"], {"route": "default"})
        self.assertEqual(payload["summary"], "summary")
        self.assertEqual(payload["case_id"], "case-1")
        self.assertEqual(payload["workflow_id"], "workflow-1")
        self.assertTrue(payload["attributes"]["existing"])

        self.assertIsNone(
            HumanHandoffSessionService._snapshot_scope_value(
                "platform",
                SimpleNamespace(),
                None,
                None,
            )
        )
        self.assertIsNone(
            HumanHandoffSessionService._snapshot_scope_value(
                "platform",
                SimpleNamespace(),
                None,
                HumanHandoffSessionDE(),
            )
        )

    async def test_append_handoff_event_uses_sender_or_room_key(self) -> None:
        service = _service()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        session = HumanHandoffSessionDE(
            tenant_id=tenant_id,
            sender_id=" ",
            room_id="room-1",
        )
        service._event_service.create = AsyncMock()

        await service._append_handoff_event(
            tenant_id=tenant_id,
            session=session,
            actor_user_id=actor_id,
            event_type="human_reply",
            decision=" sent ",
            reason=" ",
            payload={"metadata": {}},
        )

        event_payload = service._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["sender_key"], "room-1")
        self.assertEqual(event_payload["decision"], "sent")
        self.assertIsNone(event_payload["reason"])
        self.assertEqual(event_payload["source"], "human_handoff")
        self.assertEqual(event_payload["payload"]["metadata"], {})
        self.assertEqual(event_payload["payload"]["room_id"], "room-1")
        self.assertIsNone(event_payload["payload"]["session_id"])

    async def test_deliver_human_reply_returns_sent_or_failed_status(self) -> None:
        service = _service()
        session = HumanHandoffSessionDE(platform="web", conversation_id="conv-1")
        service._deliver_human_reply_or_raise = AsyncMock()

        self.assertEqual(
            await service._deliver_human_reply(
                session=session,
                content="hello",
                metadata={},
            ),
            ("sent", None),
        )

        service._deliver_human_reply_or_raise = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        status, error = await service._deliver_human_reply(
            session=session,
            content="hello",
            metadata={},
        )
        self.assertEqual(status, "failed")
        self.assertIn("RuntimeError: boom", error)

    async def test_deliver_human_reply_or_raise_routes_by_platform(self) -> None:
        service = _service()
        profile_id = uuid.uuid4()
        container = SimpleNamespace(
            web_client=SimpleNamespace(append_human_reply=AsyncMock()),
            matrix_client=SimpleNamespace(send_ingress_responses=AsyncMock()),
            line_client=SimpleNamespace(send_text_message=AsyncMock()),
            telegram_client=SimpleNamespace(send_text_message=AsyncMock()),
            signal_client=SimpleNamespace(send_text_message=AsyncMock()),
            wechat_client=SimpleNamespace(send_text_message=AsyncMock()),
            whatsapp_client=SimpleNamespace(send_text_message=AsyncMock()),
        )

        with patch.object(handoff_module.di, "container", new=container):
            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="web",
                    conversation_id="conv-1",
                ),
                content="web reply",
                metadata={"trace": "1"},
            )
            container.web_client.append_human_reply.assert_awaited_once_with(
                conversation_id="conv-1",
                content="web reply",
                metadata={"trace": "1"},
            )

            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="matrix",
                    room_id="room-1",
                ),
                content="matrix reply",
                metadata={},
            )
            container.matrix_client.send_ingress_responses.assert_awaited_once_with(
                "room-1",
                [{"type": "text", "content": "matrix reply"}],
            )

            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="line",
                    sender_id="line-user",
                    client_profile_id=profile_id,
                ),
                content="line reply",
                metadata={},
            )
            container.line_client.send_text_message.assert_awaited_once_with(
                recipient="line-user",
                text="line reply",
            )

            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="telegram",
                    sender_id="chat-1",
                    client_profile_id=profile_id,
                ),
                content="telegram reply",
                metadata={},
            )
            container.telegram_client.send_text_message.assert_awaited_once_with(
                chat_id="chat-1",
                text="telegram reply",
            )

            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="signal",
                    room_id="signal-room",
                    sender_id="signal-user",
                ),
                content="signal reply",
                metadata={},
            )
            container.signal_client.send_text_message.assert_awaited_once_with(
                recipient="signal-room",
                text="signal reply",
            )

            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="wechat",
                    sender_id="wechat-user",
                ),
                content="wechat reply",
                metadata={},
            )
            container.wechat_client.send_text_message.assert_awaited_once_with(
                recipient="wechat-user",
                text="wechat reply",
            )

            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="whatsapp",
                    sender_id="whatsapp-user",
                ),
                content="whatsapp reply",
                metadata={},
            )
            container.whatsapp_client.send_text_message.assert_awaited_once_with(
                message="whatsapp reply",
                recipient="whatsapp-user",
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "web handoff delivery requires conversation_id",
        ):
            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(platform="web"),
                content="web reply",
                metadata={},
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "matrix handoff delivery requires room_id",
        ):
            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(platform="matrix"),
                content="matrix reply",
                metadata={},
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "line handoff delivery requires a recipient",
        ):
            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(platform="line"),
                content="line reply",
                metadata={},
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "unsupported handoff delivery platform: unknown",
        ):
            await service._deliver_human_reply_or_raise(
                session=HumanHandoffSessionDE(
                    platform="unknown",
                    sender_id="recipient-1",
                ),
                content="unknown reply",
                metadata={},
            )
