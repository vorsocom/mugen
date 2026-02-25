"""Unit tests for ops_sla escalation policy evaluation and execution service."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.ops_sla.api.validation import (
    SlaEscalationEvaluateValidation,
    SlaEscalationExecuteValidation,
    SlaEscalationTestValidation,
)
from mugen.core.plugin.ops_sla.domain import (
    SlaEscalationPolicyDE,
    SlaEscalationRunDE,
)
from mugen.core.plugin.ops_sla.service.sla_escalation_policy import (
    SlaEscalationPolicyService,
)


class TestSlaEscalationPolicyService(unittest.IsolatedAsyncioTestCase):
    """Covers helper and action branches for escalation policy evaluation."""

    @staticmethod
    def _svc() -> SlaEscalationPolicyService:
        return SlaEscalationPolicyService(table="ops_sla_escalation_policy", rsg=Mock())

    @staticmethod
    def _policy(
        *,
        tenant_id: uuid.UUID,
        policy_id: uuid.UUID | None = None,
        policy_key: str = "clock.warn",
        priority: int = 100,
        is_active: bool = True,
        triggers_json: list[dict] | None = None,
        actions_json: list[dict] | None = None,
    ) -> SlaEscalationPolicyDE:
        return SlaEscalationPolicyDE(
            id=policy_id or uuid.uuid4(),
            tenant_id=tenant_id,
            policy_key=policy_key,
            priority=priority,
            is_active=is_active,
            triggers_json=triggers_json,
            actions_json=actions_json,
        )

    def test_helper_methods_for_trigger_matching_and_status(self) -> None:
        self.assertIsNone(SlaEscalationPolicyService._normalize_optional_text(None))
        self.assertIsNone(SlaEscalationPolicyService._normalize_optional_text("   "))
        self.assertEqual(
            SlaEscalationPolicyService._normalize_optional_text(" ok "),
            "ok",
        )

        payload = {"ClockId": "C-1", "nested": {"Value": 5, "items": ["a", "b"]}}
        self.assertEqual(
            SlaEscalationPolicyService._event_get(payload, "ClockId"), "C-1"
        )
        self.assertEqual(
            SlaEscalationPolicyService._event_get(payload, "clockid"), "C-1"
        )
        self.assertIsNone(SlaEscalationPolicyService._event_get(payload, "missing"))

        self.assertEqual(
            SlaEscalationPolicyService._extract_path(payload, "nested.Value"),
            5,
        )
        self.assertIsNone(
            SlaEscalationPolicyService._extract_path(payload, "nested.bad")
        )
        self.assertIsNone(SlaEscalationPolicyService._extract_path({"a": "x"}, "a.b"))
        self.assertIsNone(
            SlaEscalationPolicyService._extract_path(payload, "nested..bad")
        )

        self.assertTrue(SlaEscalationPolicyService._compare("eq", 1, 1))
        self.assertTrue(SlaEscalationPolicyService._compare("ne", 1, 2))
        self.assertFalse(SlaEscalationPolicyService._compare("in", "x", "xyz"))
        self.assertTrue(SlaEscalationPolicyService._compare("in", "x", ["x", "y"]))
        self.assertTrue(
            SlaEscalationPolicyService._compare("contains", "warned", "arn")
        )
        self.assertTrue(SlaEscalationPolicyService._compare("contains", ["a"], "a"))
        self.assertFalse(SlaEscalationPolicyService._compare("contains", 1, "a"))

        event = {"EventType": "warned", "remaining": 30}
        self.assertFalse(SlaEscalationPolicyService._matches_trigger(event, "bad"))
        self.assertTrue(
            SlaEscalationPolicyService._matches_trigger(
                event,
                {
                    "Any": [
                        {"Path": "remaining", "Op": "eq", "Value": 10},
                        {"EventType": "warned"},
                    ]
                },
            )
        )
        self.assertTrue(
            SlaEscalationPolicyService._matches_trigger(
                event,
                {
                    "All": [
                        {"Path": "remaining", "Op": "ne", "Value": 10},
                        {"EventType": "warned"},
                    ]
                },
            )
        )
        self.assertTrue(
            SlaEscalationPolicyService._matches_trigger(
                event,
                {"Path": "remaining", "Op": "eq", "Value": 30},
            )
        )
        self.assertTrue(
            SlaEscalationPolicyService._matches_trigger(
                event,
                {"Any": [], "EventType": "warned"},
            )
        )
        self.assertFalse(
            SlaEscalationPolicyService._matches_trigger(
                event,
                {"EventType": "breached"},
            )
        )

        tenant_id = uuid.uuid4()
        no_trigger_policy = self._policy(tenant_id=tenant_id, triggers_json=None)
        self.assertTrue(
            SlaEscalationPolicyService._policy_matches_event(
                policy=no_trigger_policy,
                trigger_event=event,
            )
        )
        strict_policy = self._policy(
            tenant_id=tenant_id,
            triggers_json=[{"EventType": "breached"}],
        )
        self.assertFalse(
            SlaEscalationPolicyService._policy_matches_event(
                policy=strict_policy,
                trigger_event=event,
            )
        )

        actions = SlaEscalationPolicyService._policy_actions(
            self._policy(
                tenant_id=tenant_id,
                actions_json=[
                    {"ActionType": "notify"},
                    "bad",  # type: ignore[list-item]
                ],
            )
        )
        self.assertEqual(actions, [{"ActionType": "notify"}])

        self.assertEqual(
            SlaEscalationPolicyService._action_result({}),
            {
                "ActionType": None,
                "Status": "invalid_action_type",
                "Code": "invalid_action_type",
                "Message": "ActionType must be non-empty.",
            },
        )
        self.assertEqual(
            SlaEscalationPolicyService._action_result({"ActionType": "open_decision"})[
                "Status"
            ],
            "unsupported_action_type",
        )
        self.assertEqual(
            SlaEscalationPolicyService._action_result({"ActionType": "notify"})[
                "Status"
            ],
            "planned",
        )

        self.assertEqual(SlaEscalationPolicyService._aggregate_run_status([]), "noop")
        self.assertEqual(
            SlaEscalationPolicyService._aggregate_run_status(
                [{"Status": "invalid_action_type"}]
            ),
            "failed",
        )
        self.assertEqual(
            SlaEscalationPolicyService._aggregate_run_status(
                [{"Status": "unsupported_action_type"}]
            ),
            "partial",
        )
        self.assertEqual(
            SlaEscalationPolicyService._aggregate_run_status([{"Status": "planned"}]),
            "ok",
        )

    async def test_load_policy_candidates_and_evaluate_planning_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        entity_policy = self._policy(tenant_id=tenant_id, policy_key="entity")
        id_policy = self._policy(tenant_id=tenant_id, policy_key="where-id")
        key_policy = self._policy(tenant_id=tenant_id, policy_key="target-key")
        fallback_policy = self._policy(tenant_id=tenant_id, policy_key="fallback")

        svc.get = AsyncMock(side_effect=[entity_policy, id_policy, key_policy])
        svc.list = AsyncMock(return_value=[fallback_policy])

        by_entity = await svc._load_policy_candidates(
            tenant_id=tenant_id,
            where={},
            policy_key=None,
            entity_id=entity_policy.id,
        )
        self.assertEqual([p.id for p in by_entity], [entity_policy.id])

        by_id = await svc._load_policy_candidates(
            tenant_id=tenant_id,
            where={"id": id_policy.id},
            policy_key=None,
            entity_id=None,
        )
        self.assertEqual([p.id for p in by_id], [id_policy.id])

        by_key = await svc._load_policy_candidates(
            tenant_id=tenant_id,
            where={},
            policy_key=" target-key ",
            entity_id=None,
        )
        self.assertEqual([p.id for p in by_key], [key_policy.id])

        fallback = await svc._load_policy_candidates(
            tenant_id=tenant_id,
            where={},
            policy_key=None,
            entity_id=None,
        )
        self.assertEqual([p.id for p in fallback], [fallback_policy.id])

        inactive = self._policy(
            tenant_id=tenant_id,
            policy_key="inactive",
            is_active=False,
            actions_json=[{"ActionType": "notify"}],
        )
        unmatched = self._policy(
            tenant_id=tenant_id,
            policy_key="unmatched",
            triggers_json=[{"EventType": "breached"}],
            actions_json=[{"ActionType": "notify"}],
        )
        matched = self._policy(
            tenant_id=tenant_id,
            policy_key="matched",
            triggers_json=[{"EventType": "warned"}],
            actions_json=[{"ActionType": "notify"}, {"Type": "open_decision"}],
        )
        svc._load_policy_candidates = AsyncMock(
            return_value=[inactive, unmatched, matched]
        )
        matched_policies, actions = await svc._evaluate_policies(
            tenant_id=tenant_id,
            where={},
            policy_key=None,
            trigger_event_json={"EventType": "warned"},
        )
        self.assertEqual([p.policy_key for p in matched_policies], ["matched"])
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["PolicyKey"], "matched")
        self.assertEqual(actions[0]["ActionIndex"], 0)

    async def test_action_evaluate_execute_and_test(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        policy = self._policy(
            tenant_id=tenant_id,
            policy_key="warn-policy",
            triggers_json=[{"EventType": "warned"}],
            actions_json=[{"ActionType": "notify"}, {"ActionType": "open_decision"}],
        )

        bad_eval = SlaEscalationEvaluateValidation.model_construct(
            policy_key=None,
            trigger_event_json="bad",
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_evaluate(
                tenant_id=tenant_id,
                where={},
                auth_user_id=actor_id,
                data=bad_eval,
            )
        self.assertEqual(ctx.exception.code, 400)

        svc._evaluate_policies = AsyncMock(
            return_value=([policy], [{"PolicyKey": "warn-policy"}])
        )
        evaluate_result = await svc.action_evaluate(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaEscalationEvaluateValidation(
                policy_key="warn-policy",
                trigger_event_json={"EventType": "warned"},
            ),
        )
        self.assertEqual(evaluate_result[1], 200)
        self.assertEqual(evaluate_result[0]["MatchedPolicyCount"], 1)
        self.assertEqual(evaluate_result[0]["Actions"][0]["PolicyKey"], "warn-policy")

        bad_exec = SlaEscalationExecuteValidation.model_construct(
            policy_key=None,
            trigger_event_json="bad",
            dry_run=False,
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_execute(
                tenant_id=tenant_id,
                where={},
                auth_user_id=actor_id,
                data=bad_exec,
            )
        self.assertEqual(ctx.exception.code, 400)

        svc._evaluate_policies = AsyncMock(return_value=([], []))
        noop_result = await svc.action_execute(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaEscalationExecuteValidation(
                trigger_event_json={"EventType": "warned"}
            ),
        )
        self.assertEqual(noop_result[0]["Status"], "noop")
        self.assertEqual(noop_result[0]["RunId"], None)

        svc._evaluate_policies = AsyncMock(return_value=([policy], []))
        svc._run_service.create = AsyncMock(
            return_value=SlaEscalationRunDE(id=uuid.uuid4(), tenant_id=tenant_id)
        )
        dry_run_result = await svc.action_execute(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaEscalationExecuteValidation(
                policy_key="warn-policy",
                trigger_event_json={
                    "EventType": "warned",
                    "ClockId": str(uuid.uuid4()),
                    "ClockEventId": str(uuid.uuid4()),
                    "TraceId": " trace-x ",
                },
                dry_run=True,
            ),
        )
        self.assertEqual(dry_run_result[0]["Status"], "partial")
        self.assertEqual(dry_run_result[0]["Runs"][0]["RunId"], None)
        svc._run_service.create.assert_not_awaited()

        run_id = uuid.uuid4()
        svc._run_service.create = AsyncMock(
            return_value=SlaEscalationRunDE(id=run_id, tenant_id=tenant_id)
        )
        execute_result = await svc.action_execute(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaEscalationExecuteValidation(
                policy_key="warn-policy",
                trigger_event_json={
                    "EventType": "warned",
                    "ClockId": str(uuid.uuid4()),
                    "ClockEventId": str(uuid.uuid4()),
                    "trace_id": "trace-y",
                },
                dry_run=False,
            ),
        )
        self.assertEqual(execute_result[0]["RunId"], str(run_id))
        self.assertEqual(execute_result[0]["Status"], "partial")
        create_payload = svc._run_service.create.await_args.args[0]
        self.assertEqual(create_payload["status"], "partial")
        self.assertEqual(create_payload["executed_by_user_id"], actor_id)
        self.assertEqual(create_payload["trace_id"], "trace-y")

        svc.get = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_test(
                tenant_id=tenant_id,
                where={},
                auth_user_id=actor_id,
                data=SlaEscalationTestValidation(
                    policy_key="missing",
                    sample_event_json={"EventType": "warned"},
                ),
            )
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(return_value=policy)
        unmatched_result = await svc.action_test(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaEscalationTestValidation(
                policy_key=policy.policy_key or "",
                sample_event_json={"EventType": "breached"},
            ),
        )
        self.assertFalse(unmatched_result[0]["Matched"])
        self.assertEqual(unmatched_result[0]["WouldExecute"], [])

        matched_result = await svc.action_test(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=SlaEscalationTestValidation(
                policy_key=policy.policy_key or "",
                sample_event_json={"EventType": "warned"},
            ),
        )
        self.assertTrue(matched_result[0]["Matched"])
        self.assertEqual(len(matched_result[0]["WouldExecute"]), 2)
