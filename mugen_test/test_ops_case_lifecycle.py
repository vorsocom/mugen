"""Unit tests for ops_case lifecycle and timeline behavior."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.ops_case.api.validation import (
    CaseAssignValidation,
    CaseCloseValidation,
    CaseReopenValidation,
    CaseTriageValidation,
)
from mugen.core.plugin.ops_case.domain import CaseAssignmentDE, CaseDE
from mugen.core.plugin.ops_case.service.case import CaseService


class TestOpsCaseLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests lifecycle transition actions on CaseService."""

    async def test_triage_updates_status_and_appends_event(self) -> None:
        """Triage should transition new cases and append a timeline entry."""
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        svc = CaseService(table="ops_case_case", rsg=Mock())

        current = CaseDE(
            id=case_id,
            tenant_id=tenant_id,
            status="new",
            row_version=4,
            priority="medium",
            severity="medium",
        )
        updated = CaseDE(
            id=case_id,
            tenant_id=tenant_id,
            status="triaged",
            row_version=5,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_triage(
            tenant_id=tenant_id,
            entity_id=case_id,
            where={"tenant_id": tenant_id, "id": case_id},
            auth_user_id=uuid.uuid4(),
            data=CaseTriageValidation(row_version=4, priority="high"),
        )

        self.assertEqual(resp, ("", 204))
        svc.update_with_row_version.assert_awaited_once()
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "triaged")
        self.assertEqual(changes["priority"], "high")
        svc._event_service.create.assert_awaited_once()
        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "triaged")
        self.assertEqual(event_payload["status_from"], "new")
        self.assertEqual(event_payload["status_to"], "triaged")

    async def test_close_requires_resolved_status(self) -> None:
        """Closing a non-resolved case should raise a conflict."""
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        svc = CaseService(table="ops_case_case", rsg=Mock())

        svc.get = AsyncMock(
            side_effect=[
                CaseDE(
                    id=case_id,
                    tenant_id=tenant_id,
                    status="in_progress",
                    row_version=7,
                )
            ]
        )
        svc.update_with_row_version = AsyncMock()

        with self.assertRaises(HTTPException) as ctx:
            await svc.action_close(
                tenant_id=tenant_id,
                entity_id=case_id,
                where={"tenant_id": tenant_id, "id": case_id},
                auth_user_id=uuid.uuid4(),
                data=CaseCloseValidation(row_version=7),
            )

        self.assertEqual(ctx.exception.code, 409)
        svc.update_with_row_version.assert_not_called()

    async def test_assign_records_assignment_history_and_event(self) -> None:
        """Assign should close previous assignment, append history, and log event."""
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        old_assignment_id = uuid.uuid4()
        new_assignment_id = uuid.uuid4()
        svc = CaseService(table="ops_case_case", rsg=Mock())

        current = CaseDE(
            id=case_id,
            tenant_id=tenant_id,
            status="triaged",
            row_version=2,
        )
        updated = CaseDE(
            id=case_id,
            tenant_id=tenant_id,
            status="triaged",
            row_version=3,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=updated)
        svc._assignment_service.get = AsyncMock(
            return_value=CaseAssignmentDE(
                id=old_assignment_id,
                tenant_id=tenant_id,
                case_id=case_id,
                is_active=True,
            )
        )
        svc._assignment_service.update = AsyncMock(return_value=Mock())
        svc._assignment_service.create = AsyncMock(
            return_value=CaseAssignmentDE(
                id=new_assignment_id,
                tenant_id=tenant_id,
                case_id=case_id,
                is_active=True,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        owner_id = uuid.uuid4()
        resp = await svc.action_assign(
            tenant_id=tenant_id,
            entity_id=case_id,
            where={"tenant_id": tenant_id, "id": case_id},
            auth_user_id=uuid.uuid4(),
            data=CaseAssignValidation(
                row_version=2,
                owner_user_id=owner_id,
                queue_name="ops-l2",
                reason="handoff",
            ),
        )

        self.assertEqual(resp, ("", 204))
        svc._assignment_service.update.assert_awaited_once()
        svc._assignment_service.create.assert_awaited_once()
        svc._event_service.create.assert_awaited_once()
        event_payload = svc._event_service.create.await_args.args[0]
        self.assertEqual(event_payload["event_type"], "assigned")
        self.assertEqual(
            event_payload["payload"]["assignment_id"],
            str(new_assignment_id),
        )
        self.assertEqual(event_payload["payload"]["queue_name"], "ops-l2")

    async def test_reopen_resets_terminal_timestamps(self) -> None:
        """Reopen should move case back to in-progress and clear terminal markers."""
        tenant_id = uuid.uuid4()
        case_id = uuid.uuid4()
        svc = CaseService(table="ops_case_case", rsg=Mock())

        svc.get = AsyncMock(
            return_value=CaseDE(
                id=case_id,
                tenant_id=tenant_id,
                status="closed",
                row_version=12,
            )
        )
        svc.update_with_row_version = AsyncMock(
            return_value=CaseDE(
                id=case_id,
                tenant_id=tenant_id,
                status="in_progress",
                row_version=13,
            )
        )
        svc._event_service.create = AsyncMock(return_value=Mock())

        resp = await svc.action_reopen(
            tenant_id=tenant_id,
            entity_id=case_id,
            where={"tenant_id": tenant_id, "id": case_id},
            auth_user_id=uuid.uuid4(),
            data=CaseReopenValidation(row_version=12),
        )

        self.assertEqual(resp, ("", 204))
        changes = svc.update_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(changes["status"], "in_progress")
        self.assertIsNone(changes["resolved_at"])
        self.assertIsNone(changes["closed_at"])
        self.assertIsNone(changes["cancelled_at"])

