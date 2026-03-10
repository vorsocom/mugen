"""Coverage-focused tests for agent_runtime plugin runtime services."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.contract.agent import (
    AgentRuntimePolicy,
    PlanOutcome,
    PlanOutcomeStatus,
    PlanRunMode,
    PlanRunRequest,
    PlanRunState,
    PlanRunStep,
    PlanRunStepKind,
)
from mugen.core.contract.context import ContextScope
from mugen.core.plugin.agent_runtime.model import AgentPlanRun, AgentPlanStep
from mugen.core.plugin.agent_runtime.service.runtime import (
    CodeConfiguredAgentPolicyResolver,
    RelationalAgentScheduler,
    RelationalPlanRunStore,
)


def _scope() -> ContextScope:
    return ContextScope(
        tenant_id="11111111-1111-1111-1111-111111111111",
        platform="matrix",
        channel_id="matrix",
        room_id="room-1",
        sender_id="user-1",
        conversation_id="room-1",
    )


def _request(
    *,
    mode: PlanRunMode = PlanRunMode.BACKGROUND,
    service_route_key: str | None = "support.primary",
) -> PlanRunRequest:
    return PlanRunRequest(
        mode=mode,
        scope=_scope(),
        user_message="Investigate the incident",
        service_route_key=service_route_key,
        metadata={"auth_user_id": "22222222-2222-2222-2222-222222222222"},
    )


class _FakeRunService:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, SimpleNamespace] = {}

    async def create(self, payload: dict) -> SimpleNamespace:
        now = datetime.now(timezone.utc)
        row = SimpleNamespace(
            id=uuid.uuid4(),
            created_at=now,
            updated_at=now,
            row_version=1,
            **payload,
        )
        self.rows[row.id] = row
        return row

    async def get(self, where: dict) -> SimpleNamespace | None:
        return self.rows.get(where["id"])

    async def update_with_row_version(
        self,
        where: dict,
        *,
        expected_row_version: int | None,
        changes: dict,
    ) -> SimpleNamespace | None:
        row = self.rows.get(where["id"])
        if row is None:
            return None
        if expected_row_version is not None and row.row_version != expected_row_version:
            return None
        for key, value in changes.items():
            setattr(row, key, value)
        row.row_version = int(row.row_version or 0) + 1
        row.updated_at = datetime.now(timezone.utc)
        return row

    async def list(self, *, filter_groups=None, order_by=None, limit=None) -> list:
        rows = list(self.rows.values())
        for filter_group in filter_groups or []:
            where = dict(getattr(filter_group, "where", {}) or {})
            rows = [
                row
                for row in rows
                if all(getattr(row, key) == value for key, value in where.items())
            ]
        for order in reversed(order_by or []):
            field = getattr(order, "field", None)
            rows.sort(key=lambda row: getattr(row, field))
        if limit is not None:
            rows = rows[:limit]
        return rows


class _FakeStepService:
    def __init__(self) -> None:
        self.rows: list[SimpleNamespace] = []

    async def create(self, payload: dict) -> SimpleNamespace:
        row = SimpleNamespace(
            id=uuid.uuid4(),
            row_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            **payload,
        )
        self.rows.append(row)
        return row

    async def list(self, *, filter_groups=None, order_by=None, limit=None) -> list:
        rows = list(self.rows)
        for filter_group in filter_groups or []:
            where = dict(getattr(filter_group, "where", {}) or {})
            rows = [
                row
                for row in rows
                if all(getattr(row, key) == value for key, value in where.items())
            ]
        for order in reversed(order_by or []):
            field = getattr(order, "field", None)
            rows.sort(key=lambda row: getattr(row, field))
        if limit is not None:
            rows = rows[:limit]
        return rows


class TestMugenAgentRuntimePluginRuntime(unittest.IsolatedAsyncioTestCase):
    """Exercises plugin runtime services without DI/bootstrap."""

    async def test_models_use_core_runtime_schema(self) -> None:
        self.assertEqual(AgentPlanRun.__table__.schema, "mugen")
        self.assertEqual(AgentPlanStep.__table__.schema, "mugen")
        self.assertIn("service_route_key", AgentPlanRun.__table__.c)
        self.assertIn("current_sequence_no", AgentPlanRun.__table__.c)
        self.assertIn("run_id", AgentPlanStep.__table__.c)
        self.assertIn("payload_json", AgentPlanStep.__table__.c)

    async def test_policy_resolver_applies_defaults_and_route_overrides(self) -> None:
        resolver = CodeConfiguredAgentPolicyResolver(
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    agent_runtime=SimpleNamespace(
                        enabled=True,
                        current_turn_enabled=True,
                        planner_key="planner.default",
                        capability_allow=["cap.base"],
                        routes=[
                            SimpleNamespace(
                                service_route_key="support.primary",
                                background_enabled=True,
                                planner_key="planner.route",
                                capability_allow=["cap.route", " cap.extra "],
                            )
                        ],
                    )
                )
            )
        )

        default_policy = await resolver.resolve_policy(
            _request(service_route_key="support.secondary")
        )
        route_policy = await resolver.resolve_policy(
            _request(service_route_key="support.primary")
        )

        self.assertTrue(default_policy.enabled)
        self.assertTrue(default_policy.current_turn_enabled)
        self.assertEqual(default_policy.planner_key, "planner.default")
        self.assertEqual(default_policy.capability_allow, ("cap.base",))
        self.assertEqual(route_policy.planner_key, "planner.route")
        self.assertTrue(route_policy.background_enabled)
        self.assertEqual(route_policy.capability_allow, ("cap.route", "cap.extra"))
        self.assertEqual(
            route_policy.metadata["service_route_key"],
            "support.primary",
        )

    async def test_relational_plan_run_store_round_trip_and_step_history(self) -> None:
        run_service = _FakeRunService()
        step_service = _FakeStepService()
        store = RelationalPlanRunStore(
            run_service=run_service,
            step_service=step_service,
        )

        created = await store.create_run(
            _request(),
            state=PlanRunState(goal="Investigate the incident"),
            policy=AgentRuntimePolicy(enabled=True, background_enabled=True),
        )
        created.state.summary = "Initial summary"
        created.metadata["checkpoint"] = "saved"

        saved = await store.save_run(created)
        cursor = await store.append_step(
            run_id=saved.run_id,
            step=PlanRunStep(
                run_id=saved.run_id,
                sequence_no=saved.cursor.next_sequence_no,
                step_kind=PlanRunStepKind.DECISION,
                payload={"kind": "respond"},
                occurred_at=datetime.now(timezone.utc),
            ),
        )
        loaded = await store.load_run(saved.run_id)
        steps = await store.list_steps(run_id=saved.run_id)

        self.assertEqual(saved.state.summary, "Initial summary")
        self.assertEqual(saved.metadata["checkpoint"], "saved")
        self.assertEqual(cursor.next_sequence_no, 2)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.row_version, 3)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].step_kind, PlanRunStepKind.DECISION)
        self.assertEqual(steps[0].payload["kind"], "respond")

    async def test_relational_plan_run_store_handles_leases_due_runs_and_duplicate_finalize(
        self,
    ) -> None:
        run_service = _FakeRunService()
        step_service = _FakeStepService()
        store = RelationalPlanRunStore(
            run_service=run_service,
            step_service=step_service,
        )
        created = await store.create_run(
            _request(),
            state=PlanRunState(goal="Investigate the incident"),
            policy=AgentRuntimePolicy(enabled=True, background_enabled=True),
        )
        now = datetime.now(timezone.utc)

        self.assertEqual(
            [run.run_id for run in await store.list_runnable_runs(limit=10, now=now)],
            [created.run_id],
        )

        lease = await store.acquire_lease(
            run_id=created.run_id,
            owner="worker-1",
            lease_seconds=30,
        )
        self.assertIsNotNone(lease)
        self.assertEqual(
            await store.list_runnable_runs(limit=10, now=now),
            [],
        )

        row = run_service.rows[uuid.UUID(created.run_id)]
        row.lease_expires_at = now - timedelta(seconds=5)
        due_after_expiry = await store.list_runnable_runs(limit=10, now=now)
        self.assertEqual([run.run_id for run in due_after_expiry], [created.run_id])

        await store.release_lease(run_id=created.run_id, owner="worker-1")
        self.assertIsNone(run_service.rows[uuid.UUID(created.run_id)].lease_owner)

        finalized = await store.finalize_run(
            run_id=created.run_id,
            outcome=PlanOutcome(
                status=PlanOutcomeStatus.COMPLETED,
                assistant_response="done",
            ),
        )
        duplicated = await store.finalize_run(
            run_id=created.run_id,
            outcome=PlanOutcome(
                status=PlanOutcomeStatus.FAILED,
                error_message="should_not_replace",
            ),
        )

        self.assertEqual(finalized.status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(duplicated.status, PlanOutcomeStatus.COMPLETED)
        self.assertEqual(duplicated.assistant_response, "done")
        self.assertEqual(
            await store.list_runnable_runs(limit=10, now=now),
            [],
        )

    async def test_relational_agent_scheduler_returns_due_ids_and_preserves_wait_at(
        self,
    ) -> None:
        run_store = Mock()
        run_store.list_runnable_runs = AsyncMock(
            return_value=[
                SimpleNamespace(run_id="run-1"),
                SimpleNamespace(run_id="run-2"),
            ]
        )
        scheduler = RelationalAgentScheduler(run_store=run_store)
        wake_at = datetime.now(timezone.utc) + timedelta(minutes=5)

        due_ids = await scheduler.due_run_ids(limit=2, now=None)
        scheduled = await scheduler.schedule_wait(run=Mock(), wake_at=wake_at)

        self.assertEqual(due_ids, ["run-1", "run-2"])
        self.assertEqual(scheduled, wake_at)


if __name__ == "__main__":
    unittest.main()
