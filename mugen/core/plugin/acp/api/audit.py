"""Audit emission helpers for ACP API write/action endpoints."""

from __future__ import annotations

import uuid
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import SimpleNamespace
from typing import Any, Mapping

from quart import request

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    if isinstance(value, Enum):
        return value.value

    if is_dataclass(value):
        return {f.name: _json_safe(getattr(value, f.name)) for f in fields(value)}

    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]

    return str(value)


def _parse_positive_int(raw: Any) -> int | None:
    if raw is None:
        return None

    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None

    if value <= 0:
        return None

    return value


def _resolve_snapshot_policy(
    config: SimpleNamespace,
) -> tuple[bool, bool, int | None, int | None]:
    audit_cfg = getattr(config, "audit", SimpleNamespace())

    include_before = bool(getattr(audit_cfg, "include_before_snapshot", False))
    include_after = bool(getattr(audit_cfg, "include_after_snapshot", False))

    retention_days = _parse_positive_int(getattr(audit_cfg, "retention_days", None))
    redaction_days = _parse_positive_int(getattr(audit_cfg, "redaction_days", None))

    return include_before, include_after, retention_days, redaction_days


def _resolve_request_ids(
    request_id: str | None,
    correlation_id: str | None,
) -> tuple[str | None, str | None]:
    req = request_id
    corr = correlation_id

    if req is not None and corr is not None:
        return req, corr

    try:
        headers = request.headers
    except RuntimeError:
        return req, corr

    if req is None:
        req = headers.get("X-Request-Id")

    if corr is None:
        corr = (
            headers.get("X-Correlation-Id")
            or headers.get("X-Trace-Id")
            or req
        )

    return req, corr


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
async def emit_audit_event(
    *,
    registry: IAdminRegistry,
    entity_set: str,
    entity: str,
    operation: str,
    outcome: str,
    source_plugin: str,
    actor_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    action_name: str | None = None,
    changed_fields: list[str] | None = None,
    before: Any | None = None,
    after: Any | None = None,
    meta: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
) -> None:
    """Best-effort append-only audit writer."""
    logger: ILoggingGateway = logger_provider()

    try:
        audit_resource = registry.get_resource("AuditEvents")
        audit_svc = registry.get_edm_service(audit_resource.service_key)
    except KeyError:
        return

    config: SimpleNamespace = config_provider()
    include_before, include_after, retention_days, redaction_days = (
        _resolve_snapshot_policy(config)
    )

    resolved_request_id, resolved_correlation_id = _resolve_request_ids(
        request_id,
        correlation_id,
    )

    now = datetime.now(timezone.utc)
    retention_until = (
        now + timedelta(days=retention_days) if retention_days is not None else None
    )
    redaction_due_at = (
        now + timedelta(days=redaction_days) if redaction_days is not None else None
    )

    record = {
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "entity_set": entity_set,
        "entity": entity,
        "entity_id": entity_id,
        "operation": operation,
        "action_name": action_name,
        "occurred_at": now,
        "outcome": outcome,
        "request_id": resolved_request_id,
        "correlation_id": resolved_correlation_id,
        "source_plugin": source_plugin,
        "changed_fields": (
            list(dict.fromkeys(changed_fields)) if changed_fields else None
        ),
        "before_snapshot": _json_safe(before) if include_before else None,
        "after_snapshot": _json_safe(after) if include_after else None,
        "meta": _json_safe(meta) if meta is not None else None,
        "retention_until": retention_until,
        "redaction_due_at": redaction_due_at,
        "redacted_at": None,
        "redaction_reason": None,
    }

    try:
        await audit_svc.create(record)
    except Exception as exc:  # pylint: disable=broad-except
        emit_cfg = getattr(getattr(config, "audit", SimpleNamespace()), "emit", None)
        if bool(getattr(emit_cfg, "fail_closed", False)):
            raise
        logger.debug(f"Failed to emit audit event: {exc}")
