"""Provides a CRUD service for cases and lifecycle transitions."""

__all__ = ["CaseService"]

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_case.api.validation import (
    CaseAssignValidation,
    CaseCancelValidation,
    CaseCloseValidation,
    CaseEscalateValidation,
    CaseReopenValidation,
    CaseResolveValidation,
    CaseTriageValidation,
)
from mugen.core.plugin.ops_case.contract.service.case import ICaseService
from mugen.core.plugin.ops_case.domain import CaseDE
from mugen.core.plugin.ops_case.service.case_assignment import CaseAssignmentService
from mugen.core.plugin.ops_case.service.case_event import CaseEventService


class CaseService(
    IRelationalService[CaseDE],
    ICaseService,
):
    """A CRUD service for operations cases."""

    _EVENT_TABLE = "ops_case_case_event"
    _ASSIGNMENT_TABLE = "ops_case_case_assignment"

    _ALLOWED_PRIORITIES = {"low", "medium", "high", "urgent"}
    _ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
    _ALLOWED_TRIAGE_TARGETS = {"triaged", "in_progress", "waiting_external"}
    _TERMINAL_STATUSES = {"resolved", "closed", "cancelled"}

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=CaseDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._event_service = CaseEventService(table=self._EVENT_TABLE, rsg=rsg)
        self._assignment_service = CaseAssignmentService(
            table=self._ASSIGNMENT_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _generate_case_number(cls) -> str:
        now = cls._now_utc()
        token = uuid.uuid4().hex[:10].upper()
        return f"CASE-{now:%Y%m%d}-{token}"

    async def create(self, values: Mapping[str, Any]) -> CaseDE:
        payload = dict(values)
        payload.setdefault("case_number", self._generate_case_number())
        created = await super().create(payload)

        if created.id is not None and created.tenant_id is not None:
            await self._append_case_event(
                tenant_id=created.tenant_id,
                case_id=created.id,
                event_type="created",
                actor_user_id=created.created_by_user_id,
                status_from=None,
                status_to=created.status,
                payload={"case_number": created.case_number},
            )

        return created

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> CaseDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Case not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _append_case_event(
        self,
        *,
        tenant_id: uuid.UUID,
        case_id: uuid.UUID,
        event_type: str,
        actor_user_id: uuid.UUID | None,
        status_from: str | None = None,
        status_to: str | None = None,
        note: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        event_values = {
            "tenant_id": tenant_id,
            "case_id": case_id,
            "event_type": event_type,
            "status_from": status_from,
            "status_to": status_to,
            "note": self._normalize_optional_text(note),
            "payload": dict(payload) if payload else None,
            "actor_user_id": actor_user_id,
            "occurred_at": self._now_utc(),
        }
        await self._event_service.create(event_values)

    async def _record_assignment(
        self,
        *,
        tenant_id: uuid.UUID,
        case_id: uuid.UUID,
        owner_user_id: uuid.UUID | None,
        queue_name: str | None,
        assigned_by_user_id: uuid.UUID,
        reason: str | None,
    ) -> uuid.UUID | None:
        active = await self._assignment_service.get(
            {
                "tenant_id": tenant_id,
                "case_id": case_id,
                "is_active": True,
            }
        )
        now = self._now_utc()

        if active is not None and active.id is not None:
            await self._assignment_service.update(
                {"tenant_id": tenant_id, "id": active.id},
                {
                    "is_active": False,
                    "unassigned_at": now,
                },
            )

        created = await self._assignment_service.create(
            {
                "tenant_id": tenant_id,
                "case_id": case_id,
                "owner_user_id": owner_user_id,
                "queue_name": queue_name,
                "assigned_by_user_id": assigned_by_user_id,
                "assigned_at": now,
                "is_active": True,
                "reason": self._normalize_optional_text(reason),
            }
        )
        return created.id

    async def _update_case_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> CaseDE:
        svc: ICrudServiceWithRowVersion[CaseDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    async def _transition_status(
        self,
        *,
        tenant_id: uuid.UUID,
        case_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        expected_row_version: int,
        from_statuses: set[str],
        to_status: str,
        event_type: str,
        note: str | None = None,
        payload: Mapping[str, Any] | None = None,
        extra_changes: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status not in from_statuses:
            message = (
                f"Case can only transition to {to_status} from "
                f"{sorted(from_statuses)}."
            )
            abort(
                409,
                message,
            )

        changes = {
            "status": to_status,
            "last_actor_user_id": auth_user_id,
        }
        if extra_changes:
            changes.update(dict(extra_changes))

        await self._update_case_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes=changes,
        )

        await self._append_case_event(
            tenant_id=tenant_id,
            case_id=case_id,
            event_type=event_type,
            actor_user_id=auth_user_id,
            status_from=current.status,
            status_to=to_status,
            note=note,
            payload=payload,
        )

        return "", 204

    async def action_triage(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseTriageValidation,
    ) -> tuple[dict[str, Any], int]:
        """Triage a newly created case."""
        target_status = (data.target_status or "triaged").strip().lower()
        if target_status not in self._ALLOWED_TRIAGE_TARGETS:
            abort(
                400,
                "TargetStatus must be triaged, in_progress, or waiting_external.",
            )

        changes: dict[str, Any] = {
            "triaged_at": self._now_utc(),
        }

        if data.priority is not None:
            priority = data.priority.strip().lower()
            if priority not in self._ALLOWED_PRIORITIES:
                abort(400, "Priority must be low, medium, high, or urgent.")
            changes["priority"] = priority

        if data.severity is not None:
            severity = data.severity.strip().lower()
            if severity not in self._ALLOWED_SEVERITIES:
                abort(400, "Severity must be low, medium, high, or critical.")
            changes["severity"] = severity

        if data.due_at is not None:
            changes["due_at"] = data.due_at
        if data.sla_target_at is not None:
            changes["sla_target_at"] = data.sla_target_at

        payload = {
            "priority": changes.get("priority"),
            "severity": changes.get("severity"),
            "due_at": data.due_at.isoformat() if data.due_at else None,
            "sla_target_at": (
                data.sla_target_at.isoformat() if data.sla_target_at else None
            ),
        }

        return await self._transition_status(
            tenant_id=tenant_id,
            case_id=entity_id,
            where=where,
            auth_user_id=auth_user_id,
            expected_row_version=int(data.row_version),
            from_statuses={"new"},
            to_status=target_status,
            event_type="triaged",
            note=data.note,
            payload=payload,
            extra_changes=changes,
        )

    async def action_assign(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseAssignValidation,
    ) -> tuple[dict[str, Any], int]:
        """Assign a case to an owner and/or queue."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status in {"closed", "cancelled"}:
            abort(409, "Closed/cancelled cases cannot be reassigned.")

        queue_name = self._normalize_optional_text(data.queue_name)
        reason = self._normalize_optional_text(data.reason)

        await self._update_case_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "owner_user_id": data.owner_user_id,
                "queue_name": queue_name,
                "last_actor_user_id": auth_user_id,
            },
        )

        assignment_id = await self._record_assignment(
            tenant_id=tenant_id,
            case_id=entity_id,
            owner_user_id=data.owner_user_id,
            queue_name=queue_name,
            assigned_by_user_id=auth_user_id,
            reason=reason,
        )

        await self._append_case_event(
            tenant_id=tenant_id,
            case_id=entity_id,
            event_type="assigned",
            actor_user_id=auth_user_id,
            status_from=current.status,
            status_to=current.status,
            note=data.note,
            payload={
                "assignment_id": str(assignment_id) if assignment_id else None,
                "owner_user_id": (
                    str(data.owner_user_id) if data.owner_user_id else None
                ),
                "queue_name": queue_name,
                "reason": reason,
            },
        )

        return "", 204

    async def action_escalate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseEscalateValidation,
    ) -> tuple[dict[str, Any], int]:
        """Escalate a case and increase its escalation level."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status in self._TERMINAL_STATUSES:
            abort(409, "Resolved/closed/cancelled cases cannot be escalated.")

        current_level = int(current.escalation_level or 0)
        target_level = (
            int(data.escalation_level)
            if data.escalation_level is not None
            else current_level + 1
        )

        if target_level <= current_level:
            abort(409, "EscalationLevel must be greater than the current level.")

        await self._update_case_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "is_escalated": True,
                "escalation_level": target_level,
                "escalated_at": self._now_utc(),
                "escalated_by_user_id": auth_user_id,
                "last_actor_user_id": auth_user_id,
            },
        )

        reason = self._normalize_optional_text(data.reason)
        await self._append_case_event(
            tenant_id=tenant_id,
            case_id=entity_id,
            event_type="escalated",
            actor_user_id=auth_user_id,
            status_from=current.status,
            status_to=current.status,
            note=data.note,
            payload={
                "escalation_level": target_level,
                "reason": reason,
            },
        )

        return "", 204

    async def action_resolve(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseResolveValidation,
    ) -> tuple[dict[str, Any], int]:
        """Resolve a case."""
        resolution_summary = self._normalize_optional_text(data.resolution_summary)
        return await self._transition_status(
            tenant_id=tenant_id,
            case_id=entity_id,
            where=where,
            auth_user_id=auth_user_id,
            expected_row_version=int(data.row_version),
            from_statuses={"triaged", "in_progress", "waiting_external"},
            to_status="resolved",
            event_type="resolved",
            note=data.note,
            payload={"resolution_summary": resolution_summary},
            extra_changes={
                "resolved_at": self._now_utc(),
                "closed_at": None,
                "cancelled_at": None,
                "cancellation_reason": None,
                "resolution_summary": resolution_summary,
            },
        )

    async def action_close(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseCloseValidation,
    ) -> tuple[dict[str, Any], int]:
        """Close a resolved case."""
        return await self._transition_status(
            tenant_id=tenant_id,
            case_id=entity_id,
            where=where,
            auth_user_id=auth_user_id,
            expected_row_version=int(data.row_version),
            from_statuses={"resolved"},
            to_status="closed",
            event_type="closed",
            note=data.note,
            extra_changes={"closed_at": self._now_utc()},
        )

    async def action_reopen(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseReopenValidation,
    ) -> tuple[dict[str, Any], int]:
        """Reopen a previously resolved, closed, or cancelled case."""
        return await self._transition_status(
            tenant_id=tenant_id,
            case_id=entity_id,
            where=where,
            auth_user_id=auth_user_id,
            expected_row_version=int(data.row_version),
            from_statuses={"resolved", "closed", "cancelled"},
            to_status="in_progress",
            event_type="reopened",
            note=data.note,
            extra_changes={
                "resolved_at": None,
                "closed_at": None,
                "cancelled_at": None,
                "cancellation_reason": None,
            },
        )

    async def action_cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: CaseCancelValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel a case."""
        reason = self._normalize_optional_text(data.reason)
        return await self._transition_status(
            tenant_id=tenant_id,
            case_id=entity_id,
            where=where,
            auth_user_id=auth_user_id,
            expected_row_version=int(data.row_version),
            from_statuses={"new", "triaged", "in_progress", "waiting_external"},
            to_status="cancelled",
            event_type="cancelled",
            note=data.note,
            payload={"reason": reason},
            extra_changes={
                "cancelled_at": self._now_utc(),
                "cancellation_reason": reason,
            },
        )
