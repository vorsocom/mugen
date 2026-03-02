"""ACP foundation helpers for idempotency and schema-binding enforcement."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from quart import abort, make_response, request

from mugen.core import di
from mugen.core.plugin.acp.constants import GLOBAL_TENANT_ID
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry


def _config_provider():
    return di.container.config


def _normalize_tenant_id(tenant_id: uuid.UUID | None) -> uuid.UUID:
    return tenant_id if tenant_id is not None else GLOBAL_TENANT_ID


def _canonical_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()  # noqa: S324


def _default_scope(entity_set: str, action_name: str | None) -> str:
    if action_name is None:
        return f"acp:create:{entity_set}"
    return f"acp:action:{entity_set}:{action_name}"


def _resolve_dedup_service(registry: IAdminRegistry):
    try:
        resource = registry.get_resource("DedupRecords")
    except KeyError:
        return None

    return registry.get_edm_service(resource.service_key)


def _build_idempotency_context(
    *,
    tenant_id: uuid.UUID | None,
    entity_set: str,
    action_name: str | None,
    payload: Any,
) -> dict[str, Any] | None:
    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if idempotency_key == "":
        return None

    scope = request.headers.get("X-Idempotency-Scope") or _default_scope(
        entity_set, action_name
    )
    scope = scope.strip()
    if scope == "":
        scope = _default_scope(entity_set, action_name)

    hash_override = (request.headers.get("X-Idempotency-Request-Hash") or "").strip()
    request_hash = hash_override or _canonical_json_hash(
        {
            "tenant_id": str(_normalize_tenant_id(tenant_id)),
            "entity_set": entity_set,
            "action_name": action_name,
            "payload": payload,
        }
    )

    owner_instance = (
        request.headers.get("X-Request-Id")
        or request.headers.get("X-Correlation-Id")
        or request.headers.get("X-Trace-Id")
    )

    return {
        "tenant_id": _normalize_tenant_id(tenant_id),
        "scope": scope,
        "idempotency_key": idempotency_key,
        "request_hash": request_hash,
        "owner_instance": owner_instance,
    }


async def acquire_idempotency(
    *,
    registry: IAdminRegistry,
    tenant_id: uuid.UUID | None,
    entity_set: str,
    action_name: str | None,
    payload: Any,
) -> dict[str, Any]:
    """Try idempotency acquire and return state for commit/replay handling."""
    context = _build_idempotency_context(
        tenant_id=tenant_id,
        entity_set=entity_set,
        action_name=action_name,
        payload=payload,
    )
    if context is None:
        return {
            "enabled": False,
        }

    dedup_svc = _resolve_dedup_service(registry)
    if dedup_svc is None:
        return {
            "enabled": False,
        }

    result = await dedup_svc.acquire(**context)
    decision = result.get("decision")

    if decision == "conflict":
        abort(409, result.get("message") or "Idempotency request hash mismatch.")

    if decision == "in_progress":
        abort(409, "Idempotent request is currently in progress.")

    if decision == "replay":
        replay_payload = result.get("response_payload")
        replay_status = int(result.get("response_code") or 200)
        response = await make_response(
            replay_payload if replay_payload is not None else "",
            replay_status,
        )
        response.headers["X-Idempotency-Replayed"] = "true"
        return {
            "enabled": True,
            "replay_response": response,
            "record_id": result.get("record").id if result.get("record") else None,
        }

    record = result.get("record")
    return {
        "enabled": True,
        "record_id": record.id if record is not None else None,
    }


async def commit_idempotency_success(
    *,
    registry: IAdminRegistry,
    idempotency_state: dict[str, Any],
    response_code: int,
    response_payload: Any,
    result_ref: str | None = None,
) -> None:
    """Commit successful response envelope for an acquired idempotency state."""
    if not idempotency_state.get("enabled"):
        return

    record_id = idempotency_state.get("record_id")
    if record_id is None:
        return

    dedup_svc = _resolve_dedup_service(registry)
    if dedup_svc is None:
        return

    await dedup_svc.commit_success(
        entity_id=record_id,
        response_code=int(response_code),
        response_payload=response_payload,
        result_ref=result_ref,
    )


async def commit_idempotency_failure(
    *,
    registry: IAdminRegistry,
    idempotency_state: dict[str, Any],
    response_code: int,
    response_payload: Any,
    error_code: str | None,
    error_message: str | None,
) -> None:
    """Commit failed response envelope for an acquired idempotency state."""
    if not idempotency_state.get("enabled"):
        return

    record_id = idempotency_state.get("record_id")
    if record_id is None:
        return

    dedup_svc = _resolve_dedup_service(registry)
    if dedup_svc is None:
        return

    await dedup_svc.commit_failure(
        entity_id=record_id,
        response_code=int(response_code),
        response_payload=response_payload,
        error_code=error_code,
        error_message=error_message,
    )


def _enforce_bindings_enabled(config_provider=_config_provider) -> bool:
    try:
        cfg = config_provider()
    except Exception:  # pylint: disable=broad-exception-caught
        return False
    acp_cfg = getattr(cfg, "acp", None)
    if acp_cfg is None:
        return False
    schema_registry_cfg = getattr(acp_cfg, "schema_registry", None)
    if schema_registry_cfg is None:
        return False
    return bool(getattr(schema_registry_cfg, "enforce_bindings", False))


def _resolve_schema_services(registry: IAdminRegistry):
    try:
        schema_resource = registry.get_resource("Schemas")
        binding_resource = registry.get_resource("SchemaBindings")
    except KeyError:
        return None, None

    schema_svc = registry.get_edm_service(schema_resource.service_key)
    binding_svc = registry.get_edm_service(binding_resource.service_key)
    return schema_svc, binding_svc


async def enforce_schema_bindings(
    *,
    registry: IAdminRegistry,
    tenant_id: uuid.UUID | None,
    resource_namespace: str,
    entity_set: str,
    action_name: str | None,
    payload: Any,
    binding_kind: str,
    config_provider=_config_provider,
) -> None:
    """Enforce active schema bindings for a create/action request."""
    if not _enforce_bindings_enabled(config_provider=config_provider):
        return

    schema_svc, binding_svc = _resolve_schema_services(registry)
    if schema_svc is None or binding_svc is None:
        return

    normalized_tenant_id = _normalize_tenant_id(tenant_id)
    bindings = await binding_svc.list_active_bindings(
        tenant_id=normalized_tenant_id,
        target_namespace=resource_namespace,
        target_entity_set=entity_set,
        target_action=action_name,
        binding_kind=binding_kind,
    )

    all_errors: list[str] = []
    for binding in bindings:
        _, errors = await schema_svc.validate_payload(
            tenant_id=normalized_tenant_id,
            schema_definition_id=binding.schema_definition_id,
            key=None,
            version=None,
            payload=payload,
        )

        if errors and bool(binding.is_required):
            all_errors.extend(errors)

    if all_errors:
        formatted = "; ".join(all_errors[:10])
        abort(400, f"Schema binding validation failed: {formatted}")
