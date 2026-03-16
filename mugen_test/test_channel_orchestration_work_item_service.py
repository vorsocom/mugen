"""Unit tests for channel_orchestration WorkItemService branch coverage."""

from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.channel_orchestration.api.validation import (
    WorkItemCreateFromChannelValidation,
    WorkItemLinkToCaseValidation,
    WorkItemReplayValidation,
)
from mugen.core.plugin.channel_orchestration.domain import WorkItemDE
from mugen.core.plugin.channel_orchestration.service import work_item as work_item_mod
from mugen.core.plugin.channel_orchestration.service.work_item import WorkItemService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


class TestWorkItemService(unittest.IsolatedAsyncioTestCase):
    """Covers helper and action branches for canonical work-item handling."""

    @staticmethod
    def _svc() -> WorkItemService:
        return WorkItemService(table="channel_orchestration_work_item", rsg=Mock())

    def test_helper_methods_cover_normalization_trace_and_canonicalize(self) -> None:
        now = WorkItemService._now_utc()
        self.assertIsNotNone(now.tzinfo)

        self.assertIsNone(WorkItemService._normalize_optional_text(None))
        self.assertIsNone(WorkItemService._normalize_optional_text("  "))
        self.assertEqual(WorkItemService._normalize_optional_text(" x "), "x")
        self.assertEqual(WorkItemService._resolve_trace_id(" trace-1 "), "trace-1")

        forced = uuid.uuid4()
        with patch.object(work_item_mod.uuid, "uuid4", return_value=forced):
            self.assertEqual(WorkItemService._resolve_trace_id(None), str(forced))

        raw_uuid = uuid.uuid4()
        aware = datetime(2026, 2, 16, 9, 0, tzinfo=timezone.utc)
        naive = datetime(2026, 2, 16, 10, 0)
        canonical = WorkItemService._canonicalize(
            {
                "b": {"y": (2, 1), "x": {3, 2}},
                "a": [raw_uuid, naive, aware],
            }
        )
        self.assertEqual(list(canonical.keys()), ["a", "b"])
        self.assertEqual(canonical["a"][0], str(raw_uuid))
        self.assertEqual(canonical["a"][1], "2026-02-16T10:00:00+00:00")
        self.assertEqual(canonical["a"][2], "2026-02-16T09:00:00+00:00")
        self.assertEqual(canonical["b"]["y"], [2, 1])
        self.assertEqual(canonical["b"]["x"], [2, 3])

    def test_integrity_constraint_name_and_classifier_branches(self) -> None:
        diag_orig = Exception("duplicate")
        diag_orig.diag = type(  # type: ignore[attr-defined]
            "Diag",
            (),
            {"constraint_name": "ux_chorch_work_item__tenant_trace_id"},
        )()
        diag_error = IntegrityError("insert", {"trace_id": "t"}, diag_orig)
        self.assertEqual(
            WorkItemService._integrity_constraint_name(diag_error),
            "ux_chorch_work_item__tenant_trace_id",
        )
        self.assertTrue(WorkItemService._is_trace_unique_conflict(diag_error))

        text_error = IntegrityError(
            "insert",
            {"trace_id": "t"},
            Exception(
                (
                    "duplicate key value violates unique constraint "
                    '"ux_chorch_work_item__tenant_trace_id"'
                )
            ),
        )
        self.assertEqual(
            WorkItemService._integrity_constraint_name(text_error),
            "ux_chorch_work_item__tenant_trace_id",
        )

        other_error = IntegrityError(
            "insert",
            {"trace_id": "t"},
            Exception('duplicate key value violates unique constraint "ux_other"'),
        )
        self.assertIsNone(WorkItemService._integrity_constraint_name(other_error))
        self.assertFalse(WorkItemService._is_trace_unique_conflict(other_error))

    async def test_append_event_writes_expected_payload(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        work_item_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        now = datetime(2026, 2, 16, 9, 30, tzinfo=timezone.utc)

        svc._now_utc = Mock(return_value=now)
        svc._event_service.create = AsyncMock(return_value=Mock())

        await svc._append_event(
            tenant_id=tenant_id,
            work_item_id=work_item_id,
            actor_user_id=actor_id,
            event_type="work_item_created",
            decision=" created ",
            reason="  reason ",
            payload={"x": 1},
        )

        payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(payload["tenant_id"], tenant_id)
        self.assertEqual(payload["event_type"], "work_item_created")
        self.assertEqual(payload["decision"], "created")
        self.assertEqual(payload["reason"], "reason")
        self.assertEqual(payload["actor_user_id"], actor_id)
        self.assertEqual(payload["occurred_at"], now)
        self.assertEqual(payload["source"], "work_item")

    async def test_get_for_action_branches(self) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        current = WorkItemDE(
            id=where["id"], tenant_id=where["tenant_id"], row_version=3
        )

        svc.get = AsyncMock(return_value=current)
        resolved = await svc._get_for_action(where=where, expected_row_version=3)
        self.assertEqual(resolved.id, current.id)

        with patch.object(work_item_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=[None, current])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=3)
            self.assertEqual(ex.exception.code, 409)

    async def test_update_with_row_version_branches(self) -> None:
        svc = self._svc()
        where = {"tenant_id": uuid.uuid4(), "id": uuid.uuid4()}
        current = WorkItemDE(
            id=where["id"], tenant_id=where["tenant_id"], row_version=3
        )

        svc.update_with_row_version = AsyncMock(return_value=current)
        updated = await svc._update_with_row_version(
            where=where,
            expected_row_version=3,
            changes={"trace_id": "t-1"},
        )
        self.assertEqual(updated.id, current.id)

        with patch.object(work_item_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("channel_orchestration_work_item")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={"trace_id": "t-1"},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={"trace_id": "t-1"},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_with_row_version(
                    where=where,
                    expected_row_version=3,
                    changes={"trace_id": "t-1"},
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_action_create_from_channel_replay_and_create_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        existing_id = uuid.uuid4()

        existing = WorkItemDE(
            id=existing_id,
            tenant_id=tenant_id,
            trace_id="trace-a",
            row_version=3,
            replay_count=1,
        )
        svc.get = AsyncMock(
            return_value=existing
        )
        svc._bump_replay_telemetry = AsyncMock(
            return_value=WorkItemDE(
                id=existing_id,
                tenant_id=tenant_id,
                trace_id="trace-a",
                row_version=4,
                replay_count=2,
            )
        )
        replay_result = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(source="chat", trace_id="trace-a"),
        )
        self.assertEqual(replay_result[1], 200)
        self.assertEqual(replay_result[0]["Decision"], "replay")
        self.assertEqual(replay_result[0]["WorkItemId"], str(existing_id))
        svc._bump_replay_telemetry.assert_awaited_once()

        created_id = uuid.uuid4()
        svc.get = AsyncMock(return_value=None)
        svc.create = AsyncMock(
            return_value=WorkItemDE(
                id=created_id,
                tenant_id=tenant_id,
                trace_id="trace-b",
                source="chat",
                participants={"k": "v"},
                content={"text": "hello"},
            )
        )
        svc._append_event = AsyncMock()
        created_result = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(
                source=" chat ",
                trace_id="trace-b",
                participants={"z": 1, "a": 2},
                content={"body": "x"},
                attachments=[{"b": 2, "a": 1}],
                signals={"rank": 5},
                extractions={"ticket": "OPS-1"},
                linked_case_id=uuid.uuid4(),
                linked_workflow_instance_id=uuid.uuid4(),
                note=" seeded ",
            ),
        )
        self.assertEqual(created_result[1], 201)
        self.assertEqual(created_result[0]["Decision"], "created")
        create_payload = svc.create.await_args.args[0]
        self.assertEqual(create_payload["source"], "chat")
        self.assertEqual(list(create_payload["participants"].keys()), ["a", "z"])
        svc._append_event.assert_awaited_once()

        svc.get = AsyncMock(return_value=None)
        svc.create = AsyncMock(return_value=WorkItemDE(id=None, tenant_id=tenant_id))
        svc._append_event = AsyncMock()
        idless_result = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(source="chat"),
        )
        self.assertEqual(idless_result[1], 201)
        svc._append_event.assert_not_awaited()

    async def test_action_create_from_channel_unique_trace_race_returns_replay(
        self,
    ) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        existing_id = uuid.uuid4()

        existing = WorkItemDE(
            id=existing_id,
            tenant_id=tenant_id,
            trace_id="trace-race",
            row_version=3,
            replay_count=4,
        )
        svc.get = AsyncMock(side_effect=[None, existing])
        svc.create = AsyncMock(
            side_effect=IntegrityError(
                "insert",
                {"trace_id": "trace-race"},
                Exception(
                    (
                        "duplicate key value violates unique constraint "
                        '"ux_chorch_work_item__tenant_trace_id"'
                    )
                ),
            )
        )
        svc._bump_replay_telemetry = AsyncMock(return_value=existing)

        payload, status = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(
                source="chat",
                trace_id="trace-race",
            ),
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["Decision"], "replay")
        self.assertEqual(payload["WorkItemId"], str(existing_id))
        svc._bump_replay_telemetry.assert_awaited_once()

    async def test_bump_replay_telemetry_retries_row_version_conflicts(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        work_item_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        initial = WorkItemDE(
            id=work_item_id,
            tenant_id=tenant_id,
            row_version=2,
            replay_count=7,
        )
        refreshed = WorkItemDE(
            id=work_item_id,
            tenant_id=tenant_id,
            row_version=3,
            replay_count=7,
        )
        updated = WorkItemDE(
            id=work_item_id,
            tenant_id=tenant_id,
            row_version=4,
            replay_count=8,
            last_actor_user_id=actor_id,
        )
        svc.get = AsyncMock(return_value=refreshed)
        svc.update_with_row_version = AsyncMock(
            side_effect=[
                RowVersionConflict("channel_orchestration_work_item"),
                updated,
            ]
        )

        result = await svc._bump_replay_telemetry(
            tenant_id=tenant_id,
            work_item_id=work_item_id,
            auth_user_id=actor_id,
            current=initial,
        )

        self.assertEqual(result, updated)
        self.assertEqual(svc.update_with_row_version.await_count, 2)
        first_expected = svc.update_with_row_version.await_args_list[0].kwargs[
            "expected_row_version"
        ]
        second_expected = svc.update_with_row_version.await_args_list[1].kwargs[
            "expected_row_version"
        ]
        self.assertEqual(first_expected, 2)
        self.assertEqual(second_expected, 3)

    async def test_bump_replay_telemetry_error_and_exhausted_paths(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        work_item_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        with patch.object(work_item_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._bump_replay_telemetry(
                    tenant_id=tenant_id,
                    work_item_id=work_item_id,
                    auth_user_id=actor_id,
                    current=None,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=WorkItemDE(id=work_item_id, row_version=2))
            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._bump_replay_telemetry(
                    tenant_id=tenant_id,
                    work_item_id=work_item_id,
                    auth_user_id=actor_id,
                    current=None,
                )
            self.assertEqual(ex.exception.code, 500)

        svc.get = AsyncMock(return_value=None)
        self.assertIsNone(
            await svc._bump_replay_telemetry(
                tenant_id=tenant_id,
                work_item_id=work_item_id,
                auth_user_id=actor_id,
                current=None,
            )
        )

        retry_candidate = WorkItemDE(
            id=work_item_id,
            tenant_id=tenant_id,
            row_version=4,
            replay_count=2,
        )
        svc.get = AsyncMock(return_value=retry_candidate)
        svc.update_with_row_version = AsyncMock(return_value=None)
        self.assertIsNone(
            await svc._bump_replay_telemetry(
                tenant_id=tenant_id,
                work_item_id=work_item_id,
                auth_user_id=actor_id,
                current=None,
            )
        )
        self.assertEqual(
            svc.update_with_row_version.await_count,
            svc._REPLAY_TELEMETRY_MAX_ATTEMPTS,
        )

    async def test_action_create_from_channel_error_branches(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        payload = WorkItemCreateFromChannelValidation(source="chat", trace_id="trace-x")

        trace_conflict = IntegrityError(
            "insert",
            {"trace_id": "trace-x"},
            Exception(
                (
                    "duplicate key value violates unique constraint "
                    '"ux_chorch_work_item__tenant_trace_id"'
                )
            ),
        )

        with patch.object(work_item_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(return_value=None)
            svc.create = AsyncMock(
                side_effect=IntegrityError(
                    "insert",
                    {"trace_id": "trace-x"},
                    Exception('duplicate key value violates unique constraint "ux_other"'),
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_create_from_channel(
                    tenant_id=tenant_id,
                    where={},
                    auth_user_id=actor_id,
                    data=payload,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            svc.create = AsyncMock(side_effect=trace_conflict)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_create_from_channel(
                    tenant_id=tenant_id,
                    where={},
                    auth_user_id=actor_id,
                    data=payload,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            svc.create = AsyncMock(side_effect=trace_conflict)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_create_from_channel(
                    tenant_id=tenant_id,
                    where={},
                    auth_user_id=actor_id,
                    data=payload,
                )
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(return_value=None)
            svc.create = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_create_from_channel(
                    tenant_id=tenant_id,
                    where={},
                    auth_user_id=actor_id,
                    data=payload,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_action_create_from_channel_replay_variant_branches(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        idless_existing = WorkItemDE(id=None, tenant_id=tenant_id, trace_id="trace-idless")
        svc.get = AsyncMock(return_value=idless_existing)
        svc._bump_replay_telemetry = AsyncMock()
        payload, status = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(
                source="chat",
                trace_id="trace-idless",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["WorkItemId"], "None")
        svc._bump_replay_telemetry.assert_not_awaited()

        existing_id = uuid.uuid4()
        existing = WorkItemDE(id=existing_id, tenant_id=tenant_id, trace_id="trace-a")
        svc.get = AsyncMock(return_value=existing)
        svc._bump_replay_telemetry = AsyncMock(return_value=None)
        payload, status = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(source="chat", trace_id="trace-a"),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["WorkItemId"], str(existing_id))

        race_existing_idless = WorkItemDE(
            id=None,
            tenant_id=tenant_id,
            trace_id="trace-race-idless",
        )
        svc.get = AsyncMock(side_effect=[None, race_existing_idless])
        svc.create = AsyncMock(
            side_effect=IntegrityError(
                "insert",
                {"trace_id": "trace-race-idless"},
                Exception(
                    (
                        "duplicate key value violates unique constraint "
                        '"ux_chorch_work_item__tenant_trace_id"'
                    )
                ),
            )
        )
        svc._bump_replay_telemetry = AsyncMock()
        payload, status = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(
                source="chat",
                trace_id="trace-race-idless",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["WorkItemId"], "None")
        svc._bump_replay_telemetry.assert_not_awaited()

        race_existing = WorkItemDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            trace_id="trace-race-none-bump",
        )
        svc.get = AsyncMock(side_effect=[None, race_existing])
        svc.create = AsyncMock(
            side_effect=IntegrityError(
                "insert",
                {"trace_id": "trace-race-none-bump"},
                Exception(
                    (
                        "duplicate key value violates unique constraint "
                        '"ux_chorch_work_item__tenant_trace_id"'
                    )
                ),
            )
        )
        svc._bump_replay_telemetry = AsyncMock(return_value=None)
        payload, status = await svc.action_create_from_channel(
            tenant_id=tenant_id,
            where={},
            auth_user_id=actor_id,
            data=WorkItemCreateFromChannelValidation(
                source="chat",
                trace_id="trace-race-none-bump",
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["WorkItemId"], str(race_existing.id))

    async def test_action_link_to_case_branches_and_success(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        work_item_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_link_to_case(
                tenant_id=tenant_id,
                entity_id=None,
                where={},
                auth_user_id=actor_id,
                data=WorkItemLinkToCaseValidation(
                    row_version=1,
                    linked_case_id=uuid.uuid4(),
                ),
            )
        self.assertEqual(ctx.exception.code, 400)

        svc._get_for_action = AsyncMock(
            return_value=WorkItemDE(id=None, tenant_id=tenant_id, row_version=2)
        )
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_link_to_case(
                tenant_id=tenant_id,
                entity_id=work_item_id,
                where={},
                auth_user_id=actor_id,
                data=WorkItemLinkToCaseValidation(
                    row_version=2,
                    linked_case_id=uuid.uuid4(),
                ),
            )
        self.assertEqual(ctx.exception.code, 409)

        current = WorkItemDE(id=work_item_id, tenant_id=tenant_id, row_version=3)
        svc._get_for_action = AsyncMock(return_value=current)
        svc._update_with_row_version = AsyncMock(return_value=current)
        svc._append_event = AsyncMock()
        linked_case_id = uuid.uuid4()
        linked_workflow_instance_id = uuid.uuid4()
        result = await svc.action_link_to_case(
            tenant_id=tenant_id,
            entity_id=work_item_id,
            where={"tenant_id": tenant_id, "id": work_item_id},
            auth_user_id=actor_id,
            data=WorkItemLinkToCaseValidation(
                row_version=3,
                linked_case_id=linked_case_id,
                linked_workflow_instance_id=linked_workflow_instance_id,
                note=" linked ",
            ),
        )
        self.assertEqual(result, ("", 204))
        where_for_get = svc._get_for_action.await_args.kwargs["where"]
        self.assertEqual(where_for_get["id"], work_item_id)
        svc._append_event.assert_awaited_once()

    async def test_action_replay_branches_and_success(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        work_item_id = uuid.uuid4()
        linked_case_id = uuid.uuid4()
        linked_workflow_instance_id = uuid.uuid4()

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_replay(
                tenant_id=tenant_id,
                entity_id=None,
                where={},
                auth_user_id=uuid.uuid4(),
                data=WorkItemReplayValidation(),
            )
        self.assertEqual(ctx.exception.code, 400)

        svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_replay(
                tenant_id=tenant_id,
                entity_id=work_item_id,
                where={},
                auth_user_id=uuid.uuid4(),
                data=WorkItemReplayValidation(),
            )
        self.assertEqual(ctx.exception.code, 500)

        svc.get = AsyncMock(return_value=None)
        with self.assertRaises(HTTPException) as ctx:
            await svc.action_replay(
                tenant_id=tenant_id,
                entity_id=work_item_id,
                where={},
                auth_user_id=uuid.uuid4(),
                data=WorkItemReplayValidation(),
            )
        self.assertEqual(ctx.exception.code, 404)

        svc.get = AsyncMock(
            return_value=WorkItemDE(
                id=work_item_id,
                tenant_id=tenant_id,
                trace_id="trace-9",
                source="chat",
                participants={"p": "a"},
                content={"body": "hello"},
                attachments=[{"type": "img"}],
                signals={"confidence": 0.9},
                extractions={"intent": "support"},
                linked_case_id=linked_case_id,
                linked_workflow_instance_id=linked_workflow_instance_id,
            )
        )
        svc._bump_replay_telemetry = AsyncMock(
            return_value=WorkItemDE(
                id=work_item_id,
                tenant_id=tenant_id,
                trace_id="trace-9",
                source="chat",
                participants={"p": "a"},
                content={"body": "hello"},
                attachments=[{"type": "img"}],
                signals={"confidence": 0.9},
                extractions={"intent": "support"},
                linked_case_id=linked_case_id,
                linked_workflow_instance_id=linked_workflow_instance_id,
                row_version=2,
                replay_count=1,
            )
        )
        payload, code = await svc.action_replay(
            tenant_id=tenant_id,
            entity_id=work_item_id,
            where={"tenant_id": tenant_id, "id": work_item_id},
            auth_user_id=uuid.uuid4(),
            data=WorkItemReplayValidation(),
        )
        self.assertEqual(code, 200)
        self.assertEqual(payload["WorkItemId"], str(work_item_id))
        self.assertEqual(payload["TraceId"], "trace-9")
        self.assertEqual(payload["LinkedCaseId"], str(linked_case_id))
        self.assertEqual(
            payload["LinkedWorkflowInstanceId"],
            str(linked_workflow_instance_id),
        )
        svc._bump_replay_telemetry.assert_awaited_once()

    async def test_action_replay_telemetry_branch_variants(self) -> None:
        svc = self._svc()
        tenant_id = uuid.uuid4()
        work_item_id = uuid.uuid4()
        actor_id = uuid.uuid4()

        idless = WorkItemDE(
            id=None,
            tenant_id=tenant_id,
            trace_id="trace-idless",
            source="chat",
        )
        svc.get = AsyncMock(return_value=idless)
        svc._bump_replay_telemetry = AsyncMock()
        payload, status = await svc.action_replay(
            tenant_id=tenant_id,
            entity_id=work_item_id,
            where={"tenant_id": tenant_id, "id": work_item_id},
            auth_user_id=actor_id,
            data=WorkItemReplayValidation(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["WorkItemId"], "None")
        svc._bump_replay_telemetry.assert_not_awaited()

        with_id = WorkItemDE(
            id=work_item_id,
            tenant_id=tenant_id,
            trace_id="trace-has-id",
            source="chat",
        )
        svc.get = AsyncMock(return_value=with_id)
        svc._bump_replay_telemetry = AsyncMock(return_value=None)
        payload, status = await svc.action_replay(
            tenant_id=tenant_id,
            entity_id=work_item_id,
            where={"tenant_id": tenant_id, "id": work_item_id},
            auth_user_id=actor_id,
            data=WorkItemReplayValidation(),
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["WorkItemId"], str(work_item_id))
