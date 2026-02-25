"""Provides a CRUD service for audit correlation links."""

from __future__ import annotations

__all__ = ["AuditCorrelationLinkService"]

import uuid
from datetime import datetime, timezone
from typing import Any

from quart import abort

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import FilterGroup, OrderBy
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.audit.contract.service.audit_correlation_link import (
    IAuditCorrelationLinkService,
)
from mugen.core.plugin.audit.domain import AuditCorrelationLinkDE

_DEFAULT_MAX_ROWS = 500


class AuditCorrelationLinkService(
    IRelationalService[AuditCorrelationLinkDE],
    IAuditCorrelationLinkService,
):
    """A CRUD service for audit correlation links."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=AuditCorrelationLinkDE,
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

    @staticmethod
    def _node_key(entity_set: str | None, entity_id: uuid.UUID | None) -> str:
        return f"{entity_set or 'unknown'}:{entity_id or 'none'}"

    def _query_filter_group(
        self,
        *,
        tenant_id: uuid.UUID | None,
        trace_id: str | None,
        correlation_id: str | None,
        request_id: str | None,
    ) -> FilterGroup:
        where: dict[str, Any] = {}
        if tenant_id is not None:
            where["tenant_id"] = tenant_id

        normalized_trace_id = self._normalize_text(trace_id)
        normalized_correlation_id = self._normalize_text(correlation_id)
        normalized_request_id = self._normalize_text(request_id)

        if normalized_trace_id is not None:
            where["trace_id"] = normalized_trace_id
        if normalized_correlation_id is not None:
            where["correlation_id"] = normalized_correlation_id
        if normalized_request_id is not None:
            where["request_id"] = normalized_request_id

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

    def _format_link(self, row: AuditCorrelationLinkDE) -> dict[str, Any]:
        return {
            "Id": self._uuid_text(row.id),
            "TenantId": self._uuid_text(row.tenant_id),
            "TraceId": row.trace_id,
            "CorrelationId": row.correlation_id,
            "RequestId": row.request_id,
            "SourcePlugin": row.source_plugin,
            "EntitySet": row.entity_set,
            "EntityId": self._uuid_text(row.entity_id),
            "Operation": row.operation,
            "ActionName": row.action_name,
            "ParentEntitySet": row.parent_entity_set,
            "ParentEntityId": self._uuid_text(row.parent_entity_id),
            "OccurredAt": self._datetime_text(row.occurred_at),
            "Attributes": row.attributes,
        }

    def _build_graph(self, rows: list[AuditCorrelationLinkDE]) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[tuple[str, str], dict[str, Any]] = {}

        for row in rows:
            node_key = self._node_key(row.entity_set, row.entity_id)
            nodes.setdefault(
                node_key,
                {
                    "Id": node_key,
                    "EntitySet": row.entity_set,
                    "EntityId": self._uuid_text(row.entity_id),
                },
            )

            if row.parent_entity_set is None or row.parent_entity_id is None:
                continue

            parent_key = self._node_key(row.parent_entity_set, row.parent_entity_id)
            nodes.setdefault(
                parent_key,
                {
                    "Id": parent_key,
                    "EntitySet": row.parent_entity_set,
                    "EntityId": self._uuid_text(row.parent_entity_id),
                },
            )

            edge_key = (parent_key, node_key)
            edges.setdefault(
                edge_key,
                {
                    "From": parent_key,
                    "To": node_key,
                    "Operation": row.operation,
                    "ActionName": row.action_name,
                    "OccurredAt": self._datetime_text(row.occurred_at),
                },
            )

        return {
            "Nodes": [nodes[key] for key in sorted(nodes.keys())],
            "Edges": [edges[key] for key in sorted(edges.keys())],
        }

    async def _resolve_trace_payload(
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
        )

        rows = await self.list(
            filter_groups=[filter_group],
            order_by=[
                OrderBy("occurred_at", descending=False),
                OrderBy("id", descending=False),
            ],
            limit=max_rows,
        )

        links = [self._format_link(row) for row in rows]
        graph = self._build_graph(list(rows))

        return {
            "Links": links,
            "Graph": graph,
        }

    async def entity_set_action_resolve_trace(
        self,
        *,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Resolve links and graph projection for a trace query."""
        _ = auth_user_id
        payload = await self._resolve_trace_payload(
            tenant_id=getattr(data, "tenant_id", None),
            data=data,
        )
        return payload, 200

    async def action_resolve_trace(
        self,
        *,
        tenant_id: uuid.UUID,
        where: dict[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Resolve links and graph projection for tenant-scoped trace query."""
        _ = where
        _ = auth_user_id
        payload = await self._resolve_trace_payload(
            tenant_id=tenant_id,
            data=data,
        )
        return payload, 200
