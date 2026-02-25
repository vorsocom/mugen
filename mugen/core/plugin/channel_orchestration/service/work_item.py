"""Provides canonical intake envelope actions for WorkItem rows."""

__all__ = ["WorkItemService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.channel_orchestration.api.validation import (
    WorkItemCreateFromChannelValidation,
    WorkItemLinkToCaseValidation,
    WorkItemReplayValidation,
)
from mugen.core.plugin.channel_orchestration.contract.service.work_item import (
    IWorkItemService,
)
from mugen.core.plugin.channel_orchestration.domain import WorkItemDE
from mugen.core.plugin.channel_orchestration.service.orchestration_event import (
    OrchestrationEventService,
)


class WorkItemService(
    IRelationalService[WorkItemDE],
    IWorkItemService,
):
    """A CRUD/action service for canonical work-item envelope handling."""

    _EVENT_TABLE = "channel_orchestration_orchestration_event"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=WorkItemDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._event_service = OrchestrationEventService(
            table=self._EVENT_TABLE, rsg=rsg
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None

        clean = str(value).strip()
        return clean or None

    @classmethod
    def _resolve_trace_id(cls, trace_id: str | None) -> str:
        clean_trace = cls._normalize_optional_text(trace_id)
        if clean_trace is not None:
            return clean_trace
        return str(uuid.uuid4())

    @classmethod
    def _canonicalize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._canonicalize(raw)
                for key, raw in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, list):
            return [cls._canonicalize(item) for item in value]
        if isinstance(value, tuple):
            return [cls._canonicalize(item) for item in value]
        if isinstance(value, set):
            normalized = [cls._canonicalize(item) for item in value]
            return sorted(normalized, key=lambda item: repr(item))
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, datetime):
            dt = value
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        return value

    async def _append_event(
        self,
        *,
        tenant_id: uuid.UUID,
        work_item_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        event_type: str,
        decision: str | None,
        reason: str | None,
        payload: dict[str, Any] | None,
    ) -> None:
        await self._event_service.create(
            {
                "tenant_id": tenant_id,
                "conversation_state_id": None,
                "channel_profile_id": None,
                "sender_key": None,
                "event_type": event_type,
                "decision": self._normalize_optional_text(decision),
                "reason": self._normalize_optional_text(reason),
                "payload": payload,
                "actor_user_id": actor_user_id,
                "occurred_at": self._now_utc(),
                "source": "work_item",
            }
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> WorkItemDE:
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
            abort(404, "Work item not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> WorkItemDE:
        svc: ICrudServiceWithRowVersion[WorkItemDE] = self

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

    @staticmethod
    def _entity_where_or_abort(
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        if entity_id is None:
            abort(400, "EntityId is required for this action.")
        return {"tenant_id": tenant_id, "id": entity_id}

    async def action_create_from_channel(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,
        data: WorkItemCreateFromChannelValidation,
        entity_id: uuid.UUID | None = None,  # noqa: ARG002
    ) -> tuple[dict[str, Any], int]:
        """Create or replay a canonical work-item row by TraceId."""
        trace_id = self._resolve_trace_id(data.trace_id)

        existing = await self.get({"tenant_id": tenant_id, "trace_id": trace_id})
        if existing is not None:
            return (
                {
                    "Decision": "replay",
                    "WorkItemId": str(existing.id),
                    "TraceId": trace_id,
                },
                200,
            )

        created = await self.create(
            {
                "tenant_id": tenant_id,
                "trace_id": trace_id,
                "source": data.source.strip(),
                "participants": self._canonicalize(data.participants),
                "content": self._canonicalize(data.content),
                "attachments": self._canonicalize(data.attachments),
                "signals": self._canonicalize(data.signals),
                "extractions": self._canonicalize(data.extractions),
                "linked_case_id": data.linked_case_id,
                "linked_workflow_instance_id": data.linked_workflow_instance_id,
                "last_actor_user_id": auth_user_id,
            }
        )

        if created.id is not None:
            await self._append_event(
                tenant_id=tenant_id,
                work_item_id=created.id,
                actor_user_id=auth_user_id,
                event_type="work_item_created",
                decision="created",
                reason=self._normalize_optional_text(data.note),
                payload={
                    "trace_id": trace_id,
                    "source": data.source.strip(),
                },
            )

        return (
            {
                "Decision": "created",
                "WorkItemId": str(created.id),
                "TraceId": trace_id,
            },
            201,
        )

    async def action_link_to_case(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID | None,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WorkItemLinkToCaseValidation,
    ) -> tuple[dict[str, Any], int]:
        """Link a canonical work-item to case/workflow references."""
        entity_where = self._entity_where_or_abort(
            tenant_id=tenant_id,
            entity_id=entity_id,
        )
        expected_row_version = int(data.row_version)

        current = await self._get_for_action(
            where=entity_where if "id" not in where else where,
            expected_row_version=expected_row_version,
        )
        if current.id is None:
            abort(409, "Work item identifier is missing.")

        await self._update_with_row_version(
            where=entity_where if "id" not in where else where,
            expected_row_version=expected_row_version,
            changes={
                "linked_case_id": data.linked_case_id,
                "linked_workflow_instance_id": data.linked_workflow_instance_id,
                "last_actor_user_id": auth_user_id,
            },
        )

        await self._append_event(
            tenant_id=tenant_id,
            work_item_id=current.id,
            actor_user_id=auth_user_id,
            event_type="work_item_linked",
            decision="linked",
            reason=self._normalize_optional_text(data.note),
            payload={
                "linked_case_id": (
                    str(data.linked_case_id)
                    if data.linked_case_id is not None
                    else None
                ),
                "linked_workflow_instance_id": (
                    str(data.linked_workflow_instance_id)
                    if data.linked_workflow_instance_id is not None
                    else None
                ),
            },
        )

        return "", 204

    async def action_replay(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID | None,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: WorkItemReplayValidation,  # noqa: ARG002
    ) -> tuple[dict[str, Any], int]:
        """Return canonical work-item envelope payload for deterministic replay."""
        entity_where = self._entity_where_or_abort(
            tenant_id=tenant_id,
            entity_id=entity_id,
        )
        lookup_where = entity_where if "id" not in where else where

        try:
            current = await self.get(lookup_where)
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Work item not found.")

        payload = {
            "WorkItemId": str(current.id),
            "TraceId": current.trace_id,
            "Source": current.source,
            "Participants": current.participants,
            "Content": current.content,
            "Attachments": current.attachments,
            "Signals": current.signals,
            "Extractions": current.extractions,
            "LinkedCaseId": (
                str(current.linked_case_id)
                if current.linked_case_id is not None
                else None
            ),
            "LinkedWorkflowInstanceId": (
                str(current.linked_workflow_instance_id)
                if current.linked_workflow_instance_id is not None
                else None
            ),
        }
        return payload, 200
