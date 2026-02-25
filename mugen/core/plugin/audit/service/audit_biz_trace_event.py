"""Provides a CRUD service for audit business trace events."""

from __future__ import annotations

__all__ = ["AuditBizTraceEventService"]

import uuid
from datetime import datetime, timezone
from typing import Any

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.audit.contract.service.audit_biz_trace_event import (
    IAuditBizTraceEventService,
)
from mugen.core.plugin.audit.domain import AuditBizTraceEventDE

_DEFAULT_MAX_ROWS = 500


class AuditBizTraceEventService(
    IRelationalService[AuditBizTraceEventDE],
    IAuditBizTraceEventService,
):
    """A CRUD service for audit business trace events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AuditBizTraceEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized or None

    @staticmethod
    def _normalize_max_rows(raw: Any) -> int:
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            return _DEFAULT_MAX_ROWS
        if parsed <= 0:
            return _DEFAULT_MAX_ROWS
        return min(parsed, 5_000)

    @staticmethod
    def _uuid_text(value: uuid.UUID | None) -> str | None:
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _datetime_text(value: datetime | None) -> str | None:
        if value is None:
            return None
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()

    def _query_filter_group(
        self,
        *,
        tenant_id: uuid.UUID | None,
        trace_id: str | None,
        correlation_id: str | None,
        request_id: str | None,
        stage: str | None,
    ) -> FilterGroup:
        where: dict[str, Any] = {}
        if tenant_id is not None:
            where["tenant_id"] = tenant_id

        normalized_trace_id = self._normalize_text(trace_id)
        normalized_correlation_id = self._normalize_text(correlation_id)
        normalized_request_id = self._normalize_text(request_id)
        normalized_stage = self._normalize_text(stage)

        if normalized_trace_id is not None:
            where["trace_id"] = normalized_trace_id
        if normalized_correlation_id is not None:
            where["correlation_id"] = normalized_correlation_id
        if normalized_request_id is not None:
            where["request_id"] = normalized_request_id
        if normalized_stage is not None:
            where["stage"] = normalized_stage

        if not any(
            value is not None
            for value in (
                normalized_trace_id,
                normalized_correlation_id,
                normalized_request_id,
            )
        ):
            abort(400, "Provide TraceId, CorrelationId, or RequestId.")

        return FilterGroup(where=where)

    def _format_event(self, row: AuditBizTraceEventDE) -> dict[str, Any]:
        return {
            "Id": self._uuid_text(row.id),
            "TenantId": self._uuid_text(row.tenant_id),
            "TraceId": row.trace_id,
            "SpanId": row.span_id,
            "ParentSpanId": row.parent_span_id,
            "CorrelationId": row.correlation_id,
            "RequestId": row.request_id,
            "SourcePlugin": row.source_plugin,
            "EntitySet": row.entity_set,
            "ActionName": row.action_name,
            "Stage": row.stage,
            "StatusCode": row.status_code,
            "DurationMs": row.duration_ms,
            "DetailsJson": row.details_json,
            "OccurredAt": self._datetime_text(row.occurred_at),
        }

    async def _inspect_trace_payload(
        self,
        *,
        tenant_id: uuid.UUID | None,
        data: IValidationBase,
    ) -> dict[str, Any]:
        max_rows = self._normalize_max_rows(getattr(data, "max_rows", None))

        filter_group = self._query_filter_group(
            tenant_id=tenant_id,
            trace_id=getattr(data, "trace_id", None),
            correlation_id=getattr(data, "correlation_id", None),
            request_id=getattr(data, "request_id", None),
            stage=getattr(data, "stage", None),
        )

        rows = await self.list(
            filter_groups=[filter_group],
            order_by=[
                OrderBy("occurred_at", descending=False),
                OrderBy("id", descending=False),
            ],
            limit=max_rows,
        )

        return {
            "Events": [self._format_event(row) for row in rows],
        }

    async def entity_set_action_inspect_trace(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Inspect business-trace timeline for a trace query."""
        _ = auth_user_id
        payload = await self._inspect_trace_payload(
            tenant_id=getattr(data, "tenant_id", None),
            data=data,
        )
        return payload, 200

    async def action_inspect_trace(
        self,
        *,
        tenant_id: uuid.UUID,
        where: dict[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Inspect tenant-scoped business-trace timeline."""
        _ = where
        _ = auth_user_id
        payload = await self._inspect_trace_payload(
            tenant_id=tenant_id,
            data=data,
        )
        return payload, 200
