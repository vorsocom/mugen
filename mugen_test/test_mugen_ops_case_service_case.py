"""Branch coverage tests for ops_case CaseService."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_case.api.validation import (
    CaseAssignValidation,
    CaseCancelValidation,
    CaseEscalateValidation,
    CaseResolveValidation,
    CaseTriageValidation,
)
from mugen.core.plugin.ops_case.domain import CaseDE
from mugen.core.plugin.ops_case.service import case as case_mod
from mugen.core.plugin.ops_case.service.case import CaseService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _case(
    *,
    tenant_id: uuid.UUID,
    case_id: uuid.UUID,
    status: str,
    row_version: int = 1,
    escalation_level: int | None = None,
) -> CaseDE:
    return CaseDE(
        id=case_id,
        tenant_id=tenant_id,
        status=status,
        row_version=row_version,
        escalation_level=escalation_level,
    )


class TestMugenOpsCaseServiceCase(unittest.IsolatedAsyncioTestCase):
    """Covers helper and action edge branches in CaseService."""

    async def test_create_and_basic_helpers(self) -> None:
        self.assertIsNone(CaseService._normalize_optional_text(None))
        self.assertIsNone(CaseService._normalize_optional_text("  "))
        self.assertEqual(CaseService._normalize_optional_text(" hi "), "hi")

        fixed_now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        with (
            patch.object(CaseService, "_now_utc", return_value=fixed_now),
            patch.object(case_mod.uuid, "uuid4", return_value=uuid.UUID(int=1)),
        ):
            case_number = CaseService._generate_case_number()
        self.assertEqual(case_number, "CASE-20260214-0000000000")

        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        case_id = uuid.uuid4()
        rsg = Mock()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": case_id,
                "tenant_id": tenant_id,
                "status": "new",
                "created_by_user_id": actor_id,
                "case_number": "CASE-20260214-ABCDEF1234",
            }
        )
        svc = CaseService(table="ops_case_case", rsg=rsg)
        svc._append_case_event = AsyncMock(return_value=None)

        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "status": "new",
                "created_by_user_id": actor_id,
            }
        )
        self.assertEqual(created.id, case_id)
        payload = rsg.insert_one.await_args.args[1]
        self.assertTrue(payload["case_number"].startswith("CASE-"))
        svc._append_case_event.assert_awaited_once()

    async def test_get_for_action_and_update_with_row_version_branches(self) -> None:
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        svc = CaseService(table="ops_case_case", rsg=Mock())
        where = {"tenant_id": tenant_id, "id": case_id}
        current = _case(tenant_id=tenant_id, case_id=case_id, status="new")

        svc.get = AsyncMock(side_effect=[current])
        got = await svc._get_for_action(where=where, expected_row_version=1)
        self.assertEqual(got.id, case_id)

        with patch.object(case_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
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

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=1)
            self.assertEqual(ex.exception.code, 500)

        updated = _case(tenant_id=tenant_id, case_id=case_id, status="triaged")
        svc.update_with_row_version = AsyncMock(return_value=updated)
        result = await svc._update_case_with_row_version(
            where=where,
            expected_row_version=2,
            changes={"status": "triaged"},
        )
        self.assertEqual(result.status, "triaged")

        with patch.object(case_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("rv")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_case_with_row_version(
                    where=where,
                    expected_row_version=2,
                    changes={"status": "triaged"},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_case_with_row_version(
                    where=where,
                    expected_row_version=2,
                    changes={"status": "triaged"},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_case_with_row_version(
                    where=where,
                    expected_row_version=2,
                    changes={"status": "triaged"},
                )
            self.assertEqual(ex.exception.code, 404)

    async def test_transition_and_triage_branches(self) -> None:
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": case_id}
        svc = CaseService(table="ops_case_case", rsg=Mock())

        svc._get_for_action = AsyncMock(
            return_value=_case(tenant_id=tenant_id, case_id=case_id, status="new")
        )
        svc._update_case_with_row_version = AsyncMock(return_value=Mock())
        svc._append_case_event = AsyncMock(return_value=None)

        resp = await svc._transition_status(
            tenant_id=tenant_id,
            case_id=case_id,
            where=where,
            auth_user_id=actor_id,
            expected_row_version=1,
            from_statuses={"new"},
            to_status="triaged",
            event_type="triaged",
        )
        self.assertEqual(resp, ("", 204))
        self.assertNotIn(
            "priority",
            svc._update_case_with_row_version.await_args.kwargs["changes"],
        )

        svc._transition_status = AsyncMock(return_value=("", 204))
        due_at = datetime(2026, 2, 14, 18, 0, tzinfo=timezone.utc)
        sla_at = datetime(2026, 2, 14, 20, 0, tzinfo=timezone.utc)
        await svc.action_triage(
            tenant_id=tenant_id,
            entity_id=case_id,
            where=where,
            auth_user_id=actor_id,
            data=CaseTriageValidation(
                row_version=1,
                priority="high",
                severity="critical",
                due_at=due_at,
                sla_target_at=sla_at,
            ),
        )
        payload = svc._transition_status.await_args.kwargs["payload"]
        self.assertEqual(payload["due_at"], due_at.isoformat())
        self.assertEqual(payload["sla_target_at"], sla_at.isoformat())

        with patch.object(case_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_triage(
                    tenant_id=tenant_id,
                    entity_id=case_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=CaseTriageValidation(row_version=1, target_status="bad"),
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_triage(
                    tenant_id=tenant_id,
                    entity_id=case_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=CaseTriageValidation(row_version=1, priority="bad"),
                )
            self.assertEqual(ex.exception.code, 400)

            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_triage(
                    tenant_id=tenant_id,
                    entity_id=case_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=CaseTriageValidation(row_version=1, severity="bad"),
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_assignment_and_escalation_and_wrapper_actions(self) -> None:
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": case_id}
        svc = CaseService(table="ops_case_case", rsg=Mock())

        svc._assignment_service.get = AsyncMock(return_value=None)
        svc._assignment_service.update = AsyncMock(return_value=None)
        svc._assignment_service.create = AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4())
        )
        assignment_id = await svc._record_assignment(
            tenant_id=tenant_id,
            case_id=case_id,
            owner_user_id=actor_id,
            queue_name="ops-l2",
            assigned_by_user_id=actor_id,
            reason="handoff",
        )
        self.assertIsNotNone(assignment_id)
        svc._assignment_service.update.assert_not_called()

        svc._get_for_action = AsyncMock(
            return_value=_case(tenant_id=tenant_id, case_id=case_id, status="closed")
        )
        with patch.object(case_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_assign(
                    tenant_id=tenant_id,
                    entity_id=case_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=CaseAssignValidation(
                        row_version=1,
                        owner_user_id=actor_id,
                    ),
                )
            self.assertEqual(ex.exception.code, 409)

        svc._get_for_action = AsyncMock(
            return_value=_case(
                tenant_id=tenant_id,
                case_id=case_id,
                status="in_progress",
                escalation_level=2,
            )
        )
        with patch.object(case_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_case(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    status="resolved",
                    escalation_level=2,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_escalate(
                    tenant_id=tenant_id,
                    entity_id=case_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=CaseEscalateValidation(row_version=1),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_case(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    status="in_progress",
                    escalation_level=2,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_escalate(
                    tenant_id=tenant_id,
                    entity_id=case_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=CaseEscalateValidation(row_version=1, escalation_level=1),
                )
            self.assertEqual(ex.exception.code, 409)

        svc._get_for_action = AsyncMock(
            return_value=_case(tenant_id=tenant_id, case_id=case_id, status="triaged")
        )
        svc._update_case_with_row_version = AsyncMock(return_value=Mock())
        svc._append_case_event = AsyncMock(return_value=None)
        resp = await svc.action_escalate(
            tenant_id=tenant_id,
            entity_id=case_id,
            where=where,
            auth_user_id=actor_id,
            data=CaseEscalateValidation(row_version=1, reason="manual"),
        )
        self.assertEqual(resp, ("", 204))
        self.assertEqual(
            svc._update_case_with_row_version.await_args.kwargs["changes"][
                "escalation_level"
            ],
            1,
        )

        svc._transition_status = AsyncMock(return_value=("", 204))
        await svc.action_resolve(
            tenant_id=tenant_id,
            entity_id=case_id,
            where=where,
            auth_user_id=actor_id,
            data=CaseResolveValidation(row_version=1, resolution_summary=" fixed "),
        )
        await svc.action_cancel(
            tenant_id=tenant_id,
            entity_id=case_id,
            where=where,
            auth_user_id=actor_id,
            data=CaseCancelValidation(row_version=1, reason=" duplicate "),
        )
        self.assertEqual(svc._transition_status.await_count, 2)


if __name__ == "__main__":
    unittest.main()
