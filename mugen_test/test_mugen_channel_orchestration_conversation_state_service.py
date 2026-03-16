"""Unit tests for channel orchestration conversation state service branches."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.channel_orchestration.domain import (
    BlocklistEntryDE,
    ConversationStateDE,
    IntakeRuleDE,
    OrchestrationPolicyDE,
    RoutingRuleDE,
    ThrottleRuleDE,
)
from mugen.core.plugin.channel_orchestration.service import (
    conversation_state as conversation_state_mod,
)
from mugen.core.plugin.channel_orchestration.service.conversation_state import (
    ConversationStateService,
)


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _service() -> ConversationStateService:
    svc = ConversationStateService(
        table="channel_orchestration_conversation_state",
        rsg=Mock(),
    )
    svc._now_utc = lambda: datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
    return svc


class TestMugenChannelOrchestrationConversationStateService(
    unittest.IsolatedAsyncioTestCase
):
    """Covers helper/resolver and action branches with mocked dependencies."""

    def test_helper_methods(self) -> None:
        now = ConversationStateService._now_utc()
        self.assertEqual(now.tzinfo, timezone.utc)

        self.assertIsNone(ConversationStateService._normalize_optional_text(None))
        self.assertIsNone(ConversationStateService._normalize_optional_text("   "))
        self.assertEqual(
            ConversationStateService._normalize_optional_text(" test "),
            "test",
        )

        self.assertIsNone(ConversationStateService._normalized_casefold("  "))
        self.assertEqual(
            ConversationStateService._normalized_casefold(" HeLLo "),
            "hello",
        )

        self.assertEqual(ConversationStateService._kind_rank("intent"), 3)
        self.assertEqual(ConversationStateService._kind_rank("keyword"), 2)
        self.assertEqual(ConversationStateService._kind_rank("menu"), 1)
        self.assertEqual(ConversationStateService._kind_rank("unknown"), 0)

        no_created = IntakeRuleDE()
        self.assertEqual(ConversationStateService._rule_timestamp(no_created), 0.0)

        naive_created = IntakeRuleDE(created_at=datetime(2026, 2, 1, 8, 0, 0))
        self.assertGreater(ConversationStateService._rule_timestamp(naive_created), 0.0)

        keyed = IntakeRuleDE(
            match_kind="intent",
            priority=5,
            created_at=datetime(2026, 2, 1, 8, 0, 0, tzinfo=timezone.utc),
        )
        rank, priority, _ = ConversationStateService._rule_sort_key(keyed)
        self.assertEqual(rank, 3)
        self.assertEqual(priority, 5)

        data = SimpleNamespace(intent="Billing", keyword="Sale", menu_option="1")
        self.assertTrue(
            ConversationStateService._rule_matches(
                IntakeRuleDE(match_kind="intent", match_value="billing,support"),
                data,
            )
        )
        self.assertTrue(
            ConversationStateService._rule_matches(
                IntakeRuleDE(match_kind="keyword", match_value="sale"),
                data,
            )
        )
        self.assertTrue(
            ConversationStateService._rule_matches(
                IntakeRuleDE(match_kind="menu", match_value="1"),
                data,
            )
        )
        self.assertFalse(
            ConversationStateService._rule_matches(
                IntakeRuleDE(match_kind="intent", match_value=None),
                data,
            )
        )
        self.assertFalse(
            ConversationStateService._rule_matches(
                IntakeRuleDE(match_kind="other", match_value="x"),
                data,
            )
        )
        self.assertFalse(
            ConversationStateService._rule_matches(
                IntakeRuleDE(match_kind="intent", match_value="billing"),
                SimpleNamespace(intent=None, keyword=None, menu_option=None),
            )
        )

    async def test_get_for_action_paths(self) -> None:
        svc = _service()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}

        current = ConversationStateDE(id=where["id"], tenant_id=where["tenant_id"])
        svc.get = AsyncMock(return_value=current)
        self.assertIs(
            await svc._get_for_action(where=where, expected_row_version=7),
            current,
        )

        with patch.object(conversation_state_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=1)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=1)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=1)
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=[None, current])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=1)
            self.assertEqual(ex.exception.code, 409)

    async def test_update_with_row_version_paths(self) -> None:
        svc = _service()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        updated = ConversationStateDE(id=where["id"], tenant_id=where["tenant_id"])
        svc.update_with_row_version = AsyncMock(return_value=updated)

        self.assertIs(
            await svc._update_with_row_version(
                where=where,
                expected_row_version=3,
                changes={"status": "routed"},
            ),
            updated,
        )

        with patch.object(conversation_state_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(side_effect=RowVersionConflict("rv"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={},
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_append_event_and_filter_helpers(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        sender_key = " +1555 "

        svc._event_service.create = AsyncMock(return_value={})
        await svc._append_event(
            tenant_id=tenant_id,
            conversation_state_id=state_id,
            channel_profile_id=profile_id,
            sender_key=sender_key,
            event_type="route",
            decision=" routed ",
            reason=" reason ",
            actor_user_id=actor_id,
            payload={"x": 1},
        )
        payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(payload["sender_key"], "+1555")
        self.assertEqual(payload["decision"], "routed")
        self.assertEqual(payload["reason"], "reason")
        self.assertEqual(payload["source"], "channel_orchestration")

        rows = [
            BlocklistEntryDE(
                id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                sender_key="+1555",
                is_active=True,
            ),
            BlocklistEntryDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                sender_key="+1555",
                is_active=False,
            ),
            BlocklistEntryDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                sender_key="+1666",
                is_active=True,
            ),
            BlocklistEntryDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                sender_key="+1555",
                is_active=True,
                channel_profile_id=uuid.uuid4(),
            ),
            BlocklistEntryDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                sender_key="+1555",
                is_active=True,
                expires_at=datetime(2026, 2, 14, 11, 59, tzinfo=timezone.utc),
            ),
            BlocklistEntryDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                sender_key="+1555",
                is_active=True,
                channel_profile_id=profile_id,
                expires_at=datetime(2026, 2, 14, 12, 30, tzinfo=timezone.utc),
            ),
        ]
        svc._blocklist_service.list = AsyncMock(return_value=rows)
        match = await svc._active_blocklist_entry(
            tenant_id=tenant_id,
            sender_key="+1555",
            channel_profile_id=profile_id,
        )
        self.assertEqual(match.id, rows[-1].id)

        svc._blocklist_service.list = AsyncMock(return_value=[])
        self.assertIsNone(
            await svc._active_blocklist_entry(
                tenant_id=tenant_id,
                sender_key="+1555",
                channel_profile_id=profile_id,
            )
        )

    async def test_resolvers_and_upsert_blocklist(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        sender_key = "+1555"
        actor_id = uuid.uuid4()

        intake_rows = [
            IntakeRuleDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                channel_profile_id=profile_id,
                is_active=False,
            ),
            IntakeRuleDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                channel_profile_id=profile_id,
                is_active=True,
            ),
        ]
        svc._intake_rule_service.list = AsyncMock(return_value=intake_rows)
        candidates = await svc._candidate_intake_rules(
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].id, intake_rows[1].id)

        self.assertIsNone(await svc._resolve_policy(tenant_id=tenant_id, policy_id=None))
        policy_id = uuid.uuid4()
        svc._policy_service.get = AsyncMock(
            return_value=OrchestrationPolicyDE(id=policy_id, tenant_id=tenant_id)
        )
        policy = await svc._resolve_policy(tenant_id=tenant_id, policy_id=policy_id)
        self.assertEqual(policy.id, policy_id)

        rule_low = RoutingRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key="Queue.A",
            priority=1,
            is_active=True,
        )
        rule_high = RoutingRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key="queue.a",
            priority=99,
            is_active=True,
        )
        svc._routing_rule_service.list = AsyncMock(return_value=[rule_low, rule_high])
        routed = await svc._resolve_routing_rule(
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key="QUEUE.A",
        )
        self.assertEqual(routed.id, rule_high.id)

        self.assertIsNone(
            await svc._resolve_routing_rule(
                tenant_id=tenant_id,
                channel_profile_id=profile_id,
                route_key="missing",
            )
        )

        throttle_low = ThrottleRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            priority=1,
            is_active=True,
        )
        throttle_high = ThrottleRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            priority=10,
            is_active=True,
        )
        svc._throttle_rule_service.list = AsyncMock(
            return_value=[throttle_low, throttle_high]
        )
        resolved = await svc._resolve_throttle_rule(
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
        )
        self.assertEqual(resolved.id, throttle_high.id)
        svc._throttle_rule_service.list = AsyncMock(return_value=[])
        self.assertIsNone(
            await svc._resolve_throttle_rule(
                tenant_id=tenant_id,
                channel_profile_id=profile_id,
            )
        )

        svc._active_blocklist_entry = AsyncMock(return_value=None)
        svc._blocklist_service.create = AsyncMock(return_value={})
        svc._blocklist_service.update = AsyncMock(return_value={})
        await svc._upsert_blocklist_entry(
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key=sender_key,
            reason="throttle_violation",
            actor_user_id=actor_id,
            expires_at=svc._now_utc() + timedelta(minutes=5),
        )
        svc._blocklist_service.create.assert_awaited_once()

        existing = BlocklistEntryDE(id=uuid.uuid4(), tenant_id=tenant_id, is_active=True)
        svc._active_blocklist_entry = AsyncMock(return_value=existing)
        await svc._upsert_blocklist_entry(
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key=sender_key,
            reason="reblocked",
            actor_user_id=actor_id,
            expires_at=None,
        )
        svc._blocklist_service.update.assert_awaited()
        update_changes = svc._blocklist_service.update.await_args.args[1]
        self.assertIsNone(update_changes["unblocked_at"])
        self.assertIsNone(update_changes["unblock_reason"])

    async def test_action_branches_and_error_paths(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": state_id}

        blocked_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key=" +1555 ",
            row_version=3,
        )
        svc._get_for_action = AsyncMock(return_value=blocked_state)
        svc._active_blocklist_entry = AsyncMock(
            return_value=BlocklistEntryDE(id=uuid.uuid4(), tenant_id=tenant_id, is_active=True)
        )
        svc._update_with_row_version = AsyncMock(return_value=blocked_state)
        svc._append_event = AsyncMock(return_value=None)

        payload, status = await svc.action_evaluate_intake(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=3, intent="billing", keyword=None, menu_option=None),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["Decision"], "blocked")

        no_match_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=4,
        )
        svc._get_for_action = AsyncMock(return_value=no_match_state)
        svc._active_blocklist_entry = AsyncMock(return_value=None)
        svc._candidate_intake_rules = AsyncMock(return_value=[])
        payload, _ = await svc.action_evaluate_intake(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=4, intent="billing", keyword=None, menu_option=None),
        )
        self.assertEqual(payload["Decision"], "no_match")
        eval_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(eval_changes["status"], "awaiting_route")

        routed_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=5,
            route_key="queue.current",
        )
        rule = RoutingRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key="queue.routed",
            target_queue_name="queue.routed",
            target_service_key="svc.routed",
            owner_user_id=uuid.uuid4(),
            is_active=True,
        )
        svc._get_for_action = AsyncMock(return_value=routed_state)
        svc._resolve_routing_rule = AsyncMock(return_value=rule)
        svc._resolve_policy = AsyncMock(return_value=None)
        payload, _ = await svc.action_route(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=5,
                route_key=None,
                queue_name=None,
                owner_user_id=None,
                service_key=None,
            ),
        )
        self.assertEqual(payload["Decision"], "routed")
        route_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertFalse(route_changes["is_fallback_active"])

        escalated_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=6,
            escalation_level=1,
            policy_id=uuid.uuid4(),
        )
        svc._get_for_action = AsyncMock(return_value=escalated_state)
        svc._resolve_policy = AsyncMock(
            return_value=OrchestrationPolicyDE(
                id=escalated_state.policy_id,
                tenant_id=tenant_id,
                escalation_target="queue.escalation",
            )
        )
        payload, _ = await svc.action_escalate(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=6, escalation_level=None, reason="urgent"),
        )
        self.assertEqual(payload["Decision"], "escalated")
        esc_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(esc_changes["route_key"], "queue.escalation")

        no_rule_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=7,
            window_message_count=2,
        )
        svc._get_for_action = AsyncMock(return_value=no_rule_state)
        svc._resolve_throttle_rule = AsyncMock(return_value=None)
        payload, _ = await svc.action_apply_throttle(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=7, increment_count=1),
        )
        self.assertEqual(payload["Decision"], "allowed")
        self.assertEqual(payload["WindowCount"], 2)

        window_reset_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=8,
            window_started_at=datetime(2026, 2, 14, 11, 0, 0),
            window_message_count=10,
        )
        rule = ThrottleRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            window_seconds=60,
            max_messages=3,
            block_duration_seconds=0,
            block_on_violation=False,
            is_active=True,
        )
        svc._get_for_action = AsyncMock(return_value=window_reset_state)
        svc._resolve_throttle_rule = AsyncMock(return_value=rule)
        svc._upsert_blocklist_entry = AsyncMock(return_value=None)
        payload, _ = await svc.action_apply_throttle(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=8, increment_count=1),
        )
        self.assertEqual(payload["Decision"], "allowed")
        throttle_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(throttle_changes["window_message_count"], 1)
        self.assertIsNone(throttle_changes["throttled_until"])
        svc._upsert_blocklist_entry.assert_not_awaited()

        fallback_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=9,
        )
        svc._get_for_action = AsyncMock(return_value=fallback_state)
        payload, _ = await svc.action_set_fallback(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(
                row_version=9,
                fallback_mode=" default ",
                fallback_target=" queue.fallback ",
                reason=" operator ",
            ),
        )
        self.assertEqual(payload["Decision"], "configured")
        fallback_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(fallback_changes["fallback_mode"], "default")

        with patch.object(conversation_state_mod, "abort", side_effect=_abort_raiser):
            sender_missing = ConversationStateDE(
                id=state_id,
                tenant_id=tenant_id,
                channel_profile_id=profile_id,
                sender_key="   ",
                row_version=10,
            )
            svc._get_for_action = AsyncMock(return_value=sender_missing)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_apply_throttle(
                    tenant_id=tenant_id,
                    entity_id=state_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=SimpleNamespace(row_version=10, increment_count=1),
                )
            self.assertEqual(ex.exception.code, 409)

            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_set_fallback(
                    tenant_id=tenant_id,
                    entity_id=state_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=SimpleNamespace(
                        row_version=10,
                        fallback_mode="   ",
                        fallback_target=None,
                        reason=None,
                    ),
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_remaining_branch_edges(self) -> None:
        svc = _service()
        tenant_id = uuid.uuid4()
        state_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": state_id}

        rule_a = RoutingRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key="queue.a",
            priority=1,
            is_active=True,
        )
        rule_b = RoutingRuleDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key="queue.b",
            priority=5,
            is_active=True,
        )
        svc._routing_rule_service.list = AsyncMock(return_value=[rule_a, rule_b])
        selected = await svc._resolve_routing_rule(
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            route_key=None,
        )
        self.assertEqual(selected.id, rule_b.id)

        state_missing_sender = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="  ",
            row_version=1,
        )
        svc._get_for_action = AsyncMock(return_value=state_missing_sender)
        with patch.object(conversation_state_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_evaluate_intake(
                    tenant_id=tenant_id,
                    entity_id=state_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=SimpleNamespace(
                        row_version=1,
                        intent="billing",
                        keyword=None,
                        menu_option=None,
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

        escalated_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=2,
            escalation_level=0,
            policy_id=None,
        )
        svc._get_for_action = AsyncMock(return_value=escalated_state)
        svc._resolve_policy = AsyncMock(return_value=None)
        svc._update_with_row_version = AsyncMock(return_value=escalated_state)
        svc._append_event = AsyncMock(return_value=None)
        await svc.action_escalate(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=2, escalation_level=5, reason=None),
        )
        esc_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertNotIn("route_key", esc_changes)

        throttled_state = ConversationStateDE(
            id=state_id,
            tenant_id=tenant_id,
            channel_profile_id=profile_id,
            sender_key="+1555",
            row_version=3,
            window_started_at=svc._now_utc(),
            window_message_count=1,
        )
        svc._get_for_action = AsyncMock(return_value=throttled_state)
        svc._resolve_throttle_rule = AsyncMock(
            return_value=ThrottleRuleDE(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                channel_profile_id=profile_id,
                window_seconds=60,
                max_messages=1,
                block_duration_seconds=-1,
                block_on_violation=False,
                is_active=True,
            )
        )
        svc._upsert_blocklist_entry = AsyncMock(return_value=None)
        payload, _ = await svc.action_apply_throttle(
            tenant_id=tenant_id,
            entity_id=state_id,
            where=where,
            auth_user_id=actor_id,
            data=SimpleNamespace(row_version=3, increment_count=1),
        )
        self.assertEqual(payload["Decision"], "throttled")
        throttle_changes = svc._update_with_row_version.await_args.kwargs["changes"]
        self.assertIsNone(throttle_changes["throttled_until"])
