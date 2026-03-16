"""Unit tests for channel_orchestration rule, throttle, and fallback behavior."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.channel_orchestration.api.validation import (
    ApplyThrottleValidation,
    EvaluateIntakeValidation,
    RouteConversationValidation,
)
from mugen.core.plugin.channel_orchestration.domain import (
    ConversationStateDE,
    IntakeRuleDE,
    OrchestrationPolicyDE,
    ThrottleRuleDE,
)
from mugen.core.plugin.channel_orchestration.service.conversation_state import (
    ConversationStateService,
)


class TestChannelOrchestrationLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests orchestration state transitions for core behaviors."""

    async def test_evaluate_intake_rule_precedence_prefers_intent(self) -> None:
        tenant_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()

        svc = ConversationStateService(
            table="channel_orchestration_conversation_state",
            rsg=Mock(),
        )
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        svc._now_utc = lambda: now

        current = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+15550001111",
            row_version=2,
            status="open",
        )

        keyword_rule = IntakeRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            match_kind="keyword",
            match_value="billing",
            priority=100,
            route_key="queue.billing",
            is_active=True,
        )
        intent_rule = IntakeRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            match_kind="intent",
            match_value="billing",
            priority=100,
            route_key="queue.intent",
            is_active=True,
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._active_blocklist_entry = AsyncMock(return_value=None)
        svc._candidate_intake_rules = AsyncMock(
            return_value=[keyword_rule, intent_rule]
        )
        svc._update_with_row_version = AsyncMock(return_value=current)
        svc._append_event = AsyncMock(return_value=None)

        result = await svc.action_evaluate_intake(
            tenant_id=tenant_id,
            entity_id=state_id,
            where={"tenant_id": tenant_id, "id": state_id},
            auth_user_id=actor_id,
            data=EvaluateIntakeValidation(
                row_version=2,
                keyword="billing",
                intent="billing",
            ),
        )

        self.assertEqual(result[0]["Decision"], "matched")
        self.assertEqual(result[0]["IntakeRuleId"], str(intent_rule.id))

        changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["last_intake_rule_id"], intent_rule.id)
        self.assertEqual(changes["route_key"], "queue.intent")

    async def test_apply_throttle_can_auto_block_sender(self) -> None:
        tenant_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()

        svc = ConversationStateService(
            table="channel_orchestration_conversation_state",
            rsg=Mock(),
        )
        now = datetime(2026, 2, 14, 12, 5, tzinfo=timezone.utc)
        svc._now_utc = lambda: now

        current = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+15550002222",
            row_version=3,
            status="routed",
            window_started_at=datetime(2026, 2, 14, 12, 4, tzinfo=timezone.utc),
            window_message_count=2,
        )
        throttle_rule = ThrottleRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            window_seconds=120,
            max_messages=2,
            block_on_violation=True,
            block_duration_seconds=300,
            priority=100,
            is_active=True,
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._resolve_throttle_rule = AsyncMock(return_value=throttle_rule)
        svc._update_with_row_version = AsyncMock(return_value=current)
        svc._upsert_blocklist_entry = AsyncMock(return_value=None)
        svc._append_event = AsyncMock(return_value=None)

        result = await svc.action_apply_throttle(
            tenant_id=tenant_id,
            entity_id=state_id,
            where={"tenant_id": tenant_id, "id": state_id},
            auth_user_id=actor_id,
            data=ApplyThrottleValidation(row_version=3, increment_count=1),
        )

        self.assertEqual(result[0]["Decision"], "throttled")
        self.assertEqual(result[0]["WindowCount"], 3)

        changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertTrue(changes["is_throttled"])
        self.assertEqual(changes["status"], "throttled")

        svc._upsert_blocklist_entry.assert_awaited_once()

    async def test_route_uses_fallback_policy_when_rule_missing(self) -> None:
        tenant_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        svc = ConversationStateService(
            table="channel_orchestration_conversation_state",
            rsg=Mock(),
        )
        now = datetime(2026, 2, 14, 12, 10, tzinfo=timezone.utc)
        svc._now_utc = lambda: now

        current = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=uuid.uuid4(),
            sender_key="+15550003333",
            row_version=7,
            status="intake_matched",
            policy_id=uuid.uuid4(),
        )
        policy = OrchestrationPolicyDE(
            id=current.policy_id,
            tenant_id=tenant_id,
            fallback_policy="default_route",
            fallback_target="queue.fallback",
        )

        svc._get_for_action = AsyncMock(return_value=current)
        svc._resolve_routing_rule = AsyncMock(return_value=None)
        svc._resolve_policy = AsyncMock(return_value=policy)
        svc._update_with_row_version = AsyncMock(return_value=current)
        svc._append_event = AsyncMock(return_value=None)

        result = await svc.action_route(
            tenant_id=tenant_id,
            entity_id=state_id,
            where={"tenant_id": tenant_id, "id": state_id},
            auth_user_id=actor_id,
            data=RouteConversationValidation(row_version=7),
        )

        self.assertEqual(result[0]["Decision"], "fallback")
        self.assertEqual(result[0]["RouteKey"], "queue.fallback")

        changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "fallback")
        self.assertTrue(changes["is_fallback_active"])
        self.assertEqual(changes["fallback_mode"], "default_route")
