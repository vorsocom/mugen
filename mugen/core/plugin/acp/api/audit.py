"""Audit emission helpers for ACP API write/action endpoints."""

from __future__ import annotations

import json
import logging
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

_REDACTED_VALUE = "***REDACTED***"
_DEFAULT_BIZ_TRACE_DETAIL_BYTES = 32 * 1024


def _config_provider():
    try:
        return di.container.config
    except Exception:  # pylint: disable=broad-exception-caught
        return SimpleNamespace()


def _logger_provider():
    try:
        logger = di.container.logging_gateway
    except Exception:  # pylint: disable=broad-exception-caught
        logger = None
    if logger is None:
        return logging.getLogger()
    return logger


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
        corr = headers.get("X-Correlation-Id") or headers.get("X-Trace-Id") or req

    return req, corr


def _parse_traceparent(raw: str | None) -> tuple[str | None, str | None]:
    text = (raw or "").strip()
    if text == "":
        return None, None

    parts = text.split("-")
    if len(parts) != 4:
        return None, None

    _, trace_id, span_id, _ = parts

    if len(trace_id) != 32 or len(span_id) != 16:
        return None, None

    try:
        int(trace_id, 16)
        int(span_id, 16)
    except ValueError:
        return None, None

    return trace_id.lower(), span_id.lower()


def _resolve_trace_context(
    *,
    request_id: str | None,
    correlation_id: str | None,
    trace_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    resolved_trace_id = (trace_id or "").strip() or None
    span_id: str | None = None
    parent_span_id: str | None = None

    try:
        headers = request.headers
    except RuntimeError:
        if resolved_trace_id is None:
            resolved_trace_id = correlation_id or request_id
        return resolved_trace_id, span_id, parent_span_id

    parsed_trace_id, parsed_span_id = _parse_traceparent(headers.get("traceparent"))

    if resolved_trace_id is None:
        resolved_trace_id = (
            parsed_trace_id or headers.get("X-Trace-Id") or correlation_id or request_id
        )

    span_id = parsed_span_id

    return resolved_trace_id, span_id, parent_span_id


def _resolve_biz_trace_policy(
    config: SimpleNamespace,
) -> tuple[bool, int, set[str]]:
    audit_cfg = getattr(config, "audit", SimpleNamespace())
    biz_cfg = getattr(audit_cfg, "biz_trace", SimpleNamespace())

    enabled = bool(getattr(biz_cfg, "enabled", False))
    max_detail_bytes = _parse_positive_int(getattr(biz_cfg, "max_detail_bytes", None))
    if max_detail_bytes is None:
        max_detail_bytes = _DEFAULT_BIZ_TRACE_DETAIL_BYTES

    raw_keys = getattr(biz_cfg, "redacted_keys", [])
    redacted_keys: set[str] = set()
    if isinstance(raw_keys, (list, tuple, set)):
        for item in raw_keys:
            key = str(item).strip().lower()
            if key != "":
                redacted_keys.add(key)

    return enabled, max_detail_bytes, redacted_keys


def _redact_detail_keys(value: Any, redacted_keys: set[str]) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.lower() in redacted_keys:
                output[key] = _REDACTED_VALUE
                continue
            output[key] = _redact_detail_keys(raw_value, redacted_keys)
        return output

    if isinstance(value, list):
        return [_redact_detail_keys(item, redacted_keys) for item in value]

    if isinstance(value, tuple):
        return tuple(_redact_detail_keys(item, redacted_keys) for item in value)

    if isinstance(value, set):
        return {_redact_detail_keys(item, redacted_keys) for item in value}

    return value


def _truncate_details(value: Any, *, max_detail_bytes: int) -> Any:
    safe_value = _json_safe(value)
    detail_bytes = json.dumps(
        safe_value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    if len(detail_bytes) <= max_detail_bytes:
        return safe_value

    preview = detail_bytes[:max_detail_bytes].decode("utf-8", errors="ignore")
    return {
        "truncated": True,
        "size_bytes": len(detail_bytes),
        "max_detail_bytes": max_detail_bytes,
        "preview": preview,
    }


def _coerce_optional_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _emit_correlation_link(
    *,
    registry: IAdminRegistry,
    tenant_id: uuid.UUID | None,
    trace_id: str | None,
    correlation_id: str | None,
    request_id: str | None,
    source_plugin: str,
    entity_set: str,
    entity_id: uuid.UUID | None,
    operation: str,
    action_name: str | None,
    occurred_at: datetime,
    meta: Mapping[str, Any] | None,
    logger: ILoggingGateway,
) -> None:
    try:
        correlation_resource = registry.get_resource("AuditCorrelationLinks")
        correlation_svc = registry.get_edm_service(correlation_resource.service_key)
    except KeyError:
        return

    meta_map = meta if isinstance(meta, Mapping) else {}
    parent_entity_set = meta_map.get("ParentEntitySet") or meta_map.get(
        "parent_entity_set"
    )
    parent_entity_id = _coerce_optional_uuid(
        meta_map.get("ParentEntityId") or meta_map.get("parent_entity_id")
    )

    resolved_trace_id = (
        (trace_id or "").strip()
        or (correlation_id or "").strip()
        or (request_id or "").strip()
    )

    if resolved_trace_id == "":
        resolved_trace_id = uuid.uuid4().hex

    record = {
        "tenant_id": tenant_id,
        "trace_id": resolved_trace_id,
        "correlation_id": (correlation_id or "").strip() or None,
        "request_id": (request_id or "").strip() or None,
        "source_plugin": source_plugin,
        "entity_set": entity_set,
        "entity_id": entity_id,
        "operation": operation,
        "action_name": action_name,
        "parent_entity_set": (
            (str(parent_entity_set).strip() if parent_entity_set is not None else None)
            or None
        ),
        "parent_entity_id": parent_entity_id,
        "occurred_at": occurred_at,
        "attributes": _json_safe(meta_map) if meta_map else None,
    }

    try:
        await correlation_svc.create(record)
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug(f"Failed to emit correlation link: {exc}")


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
    trace_id: str | None = None,
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
    resolved_trace_id, _, _ = _resolve_trace_context(
        request_id=resolved_request_id,
        correlation_id=resolved_correlation_id,
        trace_id=trace_id,
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
        return

    await _emit_correlation_link(
        registry=registry,
        tenant_id=tenant_id,
        trace_id=resolved_trace_id,
        correlation_id=resolved_correlation_id,
        request_id=resolved_request_id,
        source_plugin=source_plugin,
        entity_set=entity_set,
        entity_id=entity_id,
        operation=operation,
        action_name=action_name,
        occurred_at=now,
        meta=meta,
        logger=logger,
    )


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
async def emit_biz_trace_event(
    *,
    registry: IAdminRegistry,
    stage: str,
    source_plugin: str,
    entity_set: str | None,
    action_name: str | None,
    status_code: int | None = None,
    duration_ms: int | None = None,
    details: Mapping[str, Any] | None = None,
    tenant_id: uuid.UUID | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
) -> None:
    """Best-effort writer for audit business trace events."""
    logger: ILoggingGateway = logger_provider()
    config: SimpleNamespace = config_provider()

    enabled, max_detail_bytes, redacted_keys = _resolve_biz_trace_policy(config)
    if not enabled:
        return

    try:
        biz_resource = registry.get_resource("AuditBizTraceEvents")
        biz_svc = registry.get_edm_service(biz_resource.service_key)
    except KeyError:
        return

    resolved_request_id, resolved_correlation_id = _resolve_request_ids(
        request_id,
        correlation_id,
    )
    resolved_trace_id, resolved_span_id, resolved_parent_span_id = (
        _resolve_trace_context(
            request_id=resolved_request_id,
            correlation_id=resolved_correlation_id,
            trace_id=trace_id,
        )
    )

    if span_id is not None:
        resolved_span_id = span_id
    if parent_span_id is not None:
        resolved_parent_span_id = parent_span_id

    redacted_details = _redact_detail_keys(_json_safe(details), redacted_keys)
    bounded_details = _truncate_details(
        redacted_details,
        max_detail_bytes=max_detail_bytes,
    )

    record = {
        "tenant_id": tenant_id,
        "trace_id": (
            (resolved_trace_id or "").strip()
            or (resolved_correlation_id or "").strip()
            or (resolved_request_id or "").strip()
            or uuid.uuid4().hex
        ),
        "span_id": resolved_span_id,
        "parent_span_id": resolved_parent_span_id,
        "correlation_id": resolved_correlation_id,
        "request_id": resolved_request_id,
        "source_plugin": source_plugin,
        "entity_set": entity_set,
        "action_name": action_name,
        "stage": stage,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "details_json": bounded_details,
        "occurred_at": datetime.now(timezone.utc),
    }

    try:
        await biz_svc.create(record)
    except Exception as exc:  # pylint: disable=broad-except
        emit_cfg = getattr(getattr(config, "audit", SimpleNamespace()), "emit", None)
        if bool(getattr(emit_cfg, "fail_closed", False)):
            raise
        logger.debug(f"Failed to emit biz trace event: {exc}")
