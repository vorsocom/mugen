"""Implements action API endpoints for EDM entity sets."""

import uuid
import time
from typing import Any, Mapping

from pydantic import ValidationError
from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.audit import emit_audit_event, emit_biz_trace_event
from mugen.core.plugin.acp.api.decorator.auth import permission_required
from mugen.core.plugin.acp.api.foundation import (
    acquire_idempotency,
    commit_idempotency_failure,
    commit_idempotency_success,
    enforce_schema_bindings,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service.sandbox_enforcer import (
    CapabilityDeniedError,
    ISandboxEnforcer,
)

# pylint: disable=too-many-arguments
# ylint: disable=too-many-positional-arguments
# pylint: disable=too-many-locals

_SCOPE_NONE = "none"
_SCOPE_REQUIRED = "required"
_SCOPE_OPTIONAL = "optional"


def _logger_provider():
    return di.container.logging_gateway


def _registry_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_REGISTRY)


def _sandbox_enforcer_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_SANDBOX_ENFORCER)


def _entity_name(edm_type_name: str) -> str:
    if "." in edm_type_name:
        return edm_type_name.split(".", 1)[1]
    return edm_type_name


def _request_ids() -> tuple[str | None, str | None]:
    request_id = request.headers.get("X-Request-Id")
    correlation_id = (
        request.headers.get("X-Correlation-Id")
        or request.headers.get("X-Trace-Id")
        or request_id
    )
    return request_id, correlation_id


def _tenant_scope_mode(
    *,
    registry: IAdminRegistry,
    edm_type_name: str,
) -> str:
    tenant_property = registry.schema.get_type(edm_type_name).find_property("TenantId")
    if tenant_property is None:
        return _SCOPE_NONE

    if bool(getattr(tenant_property, "nullable", False)):
        return _SCOPE_OPTIONAL

    return _SCOPE_REQUIRED


def _action_response_parts(result: Any) -> tuple[int, Any]:
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], int):
        return int(result[1]), result[0]
    return 200, result


def _optional_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _required_capabilities(action_cap: Mapping[str, Any] | None) -> tuple[str, ...]:
    if action_cap is None:
        return ()

    raw = action_cap.get("required_capabilities")
    if raw is None:
        return ()

    if isinstance(raw, str):
        text = raw.strip()
        return (text,) if text else ()

    if not isinstance(raw, (list, tuple, set)):
        return ()

    output: list[str] = []
    seen: set[str] = set()
    for item in raw:
        capability = str(item or "").strip()
        if capability == "" or capability in seen:
            continue
        seen.add(capability)
        output.append(capability)
    return tuple(output)


async def _enforce_required_capabilities(
    *,
    action_cap: Mapping[str, Any] | None,
    tenant_id: uuid.UUID | None,
    plugin_key: str,
    action: str,
    auth_user_uuid: uuid.UUID,
    entity_set: str,
    entity: str,
    entity_id: uuid.UUID | None,
    request_id: str | None,
    correlation_id: str | None,
    registry: IAdminRegistry,
    sandbox_enforcer_provider,
) -> None:
    required = _required_capabilities(action_cap)
    if not required:
        return

    enforcer: ISandboxEnforcer = sandbox_enforcer_provider()
    base_context = {
        "entity_set": entity_set,
        "action_name": action,
        "entity_id": str(entity_id) if entity_id is not None else None,
        "request_id": request_id,
        "correlation_id": correlation_id,
    }

    for capability in required:
        try:
            await enforcer.require(
                tenant_id=tenant_id,
                plugin_key=plugin_key,
                capability=capability,
                context=base_context,
            )
        except CapabilityDeniedError as exc:
            deny_meta = {
                "plugin_key": plugin_key,
                "capability": capability,
                "context": dict(base_context),
                "sandbox_context": dict(exc.context),
            }
            await emit_audit_event(
                registry=registry,
                entity_set=entity_set,
                entity=entity,
                entity_id=entity_id,
                operation="capability_denied",
                action_name=action,
                outcome="denied",
                source_plugin=plugin_key,
                actor_id=auth_user_uuid,
                tenant_id=tenant_id,
                meta=deny_meta,
                request_id=request_id,
                correlation_id=correlation_id,
            )
            abort(
                403,
                ("Capability requirement denied: " f"{plugin_key}:{capability}"),
            )


@api.post("core/acp/v1/<entity_set>/$action/<action>")
@permission_required(action_kw="action")
async def dispatch_entity_set_action(
    entity_set: str,
    action: str,
    auth_user: str,
    logger_provider=_logger_provider,
    registry_provider=_registry_provider,
    sandbox_enforcer_provider=_sandbox_enforcer_provider,
    **_,
) -> Any:
    """Dispatch an action for an EDM entity set."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    scope_mode = _tenant_scope_mode(registry=registry, edm_type_name=edm_type_name)
    if scope_mode == _SCOPE_REQUIRED:
        abort(400, "Entity set is tenant-scoped; use the tenant action endpoint.")

    svc = registry.get_edm_service(resource.service_key)
    handler_name = f"entity_set_action_{action}"
    handler = getattr(svc, handler_name, None)
    if handler is None or not callable(handler):
        abort(
            501,
            description=(
                f"Action {action!r} is declared for {entity_set!r} but service "
                f"{type(svc).__name__} does not implement {handler_name}()."
            ),
        )

    try:
        auth_user_uuid = uuid.UUID(str(auth_user))
    except ValueError as e:
        logger.error(e)
        abort(500)

    action_cap = resource.capabilities.actions.get(action)
    schema: IValidationBase = action_cap.get("schema")
    if schema is None:
        abort(501, "Data validation could not be performed.")

    try:
        action_data = schema.model_validate(data)
    except ValidationError as e:
        abort(400, str(e))

    tenant_for_capability = None
    if scope_mode == _SCOPE_OPTIONAL:
        tenant_for_capability = _optional_uuid(getattr(action_data, "tenant_id", None))

    await _enforce_required_capabilities(
        action_cap=action_cap,
        tenant_id=tenant_for_capability,
        plugin_key=resource.namespace,
        action=action,
        auth_user_uuid=auth_user_uuid,
        entity_set=entity_set,
        entity=entity,
        entity_id=None,
        request_id=request_id,
        correlation_id=correlation_id,
        registry=registry,
        sandbox_enforcer_provider=sandbox_enforcer_provider,
    )

    await enforce_schema_bindings(
        registry=registry,
        tenant_id=None,
        resource_namespace=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        payload=data,
        binding_kind="action",
    )

    idempotency_state = await acquire_idempotency(
        registry=registry,
        tenant_id=None,
        entity_set=entity_set,
        action_name=action,
        payload=data,
    )
    replay_response = idempotency_state.get("replay_response")
    if replay_response is not None:
        return replay_response

    started_at = time.perf_counter()
    await emit_biz_trace_event(
        registry=registry,
        stage="start",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )

    try:
        result = await handler(
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            operation="action",
            action_name=action,
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=auth_user_uuid,
            meta={"handler": handler_name},
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await emit_biz_trace_event(
            registry=registry,
            stage="error",
            source_plugin=resource.namespace,
            entity_set=entity_set,
            action_name=action,
            status_code=500,
            duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            details={
                "operation": "action",
                "handler": handler_name,
                "error": str(e),
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await commit_idempotency_failure(
            registry=registry,
            idempotency_state=idempotency_state,
            response_code=500,
            response_payload={"Error": "Action execution failed."},
            error_code="error",
            error_message=str(e),
        )
        abort(500)

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        operation="action",
        action_name=action,
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=auth_user_uuid,
        meta={"handler": handler_name},
        request_id=request_id,
        correlation_id=correlation_id,
    )

    response_code, response_payload = _action_response_parts(result)
    await emit_biz_trace_event(
        registry=registry,
        stage="finish",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        status_code=response_code,
        duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )
    await commit_idempotency_success(
        registry=registry,
        idempotency_state=idempotency_state,
        response_code=response_code,
        response_payload=response_payload,
    )

    return result


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>/$action/<action>")
@permission_required(action_kw="action", tenant_kw="tenant_id")
async def dispatch_entity_set_action_tenant(
    tenant_id: str,
    entity_set: str,
    action: str,
    auth_user: str,
    logger_provider=_logger_provider,
    registry_provider=_registry_provider,
    sandbox_enforcer_provider=_sandbox_enforcer_provider,
    **_,
) -> Any:
    """Dispatch a tenant-scoped action for an EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    scope_mode = _tenant_scope_mode(registry=registry, edm_type_name=edm_type_name)
    if scope_mode == _SCOPE_NONE:
        abort(400, "Entity set is not tenant-scoped.")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {tenant_id}.")

    resource = registry.get_resource(entity_set)
    svc = registry.get_edm_service(resource.service_key)

    handler_name = f"action_{action}"
    handler = getattr(svc, handler_name, None)
    if handler is None or not callable(handler):
        abort(
            501,
            description=(
                f"Action {action!r} is declared for {entity_set!r} but service "
                f"{type(svc).__name__} does not implement {handler_name}()."
            ),
        )

    try:
        auth_user_uuid = uuid.UUID(str(auth_user))
    except ValueError as e:
        logger.error(e)
        abort(500)

    action_cap = resource.capabilities.actions.get(action)
    schema: IValidationBase = action_cap.get("schema")
    if schema is None:
        abort(501, "Data validation could not be performed.")

    try:
        action_data = schema.model_validate(data)
    except ValidationError as e:
        abort(400, str(e))

    await _enforce_required_capabilities(
        action_cap=action_cap,
        tenant_id=tenant_uuid,
        plugin_key=resource.namespace,
        action=action,
        auth_user_uuid=auth_user_uuid,
        entity_set=entity_set,
        entity=entity,
        entity_id=None,
        request_id=request_id,
        correlation_id=correlation_id,
        registry=registry,
        sandbox_enforcer_provider=sandbox_enforcer_provider,
    )

    await enforce_schema_bindings(
        registry=registry,
        tenant_id=tenant_uuid,
        resource_namespace=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        payload=data,
        binding_kind="action",
    )

    idempotency_state = await acquire_idempotency(
        registry=registry,
        tenant_id=tenant_uuid,
        entity_set=entity_set,
        action_name=action,
        payload=data,
    )
    replay_response = idempotency_state.get("replay_response")
    if replay_response is not None:
        return replay_response

    started_at = time.perf_counter()
    await emit_biz_trace_event(
        registry=registry,
        stage="start",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        tenant_id=tenant_uuid,
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )

    where = {"tenant_id": tenant_uuid}

    try:
        result = await handler(
            tenant_id=tenant_uuid,
            where=where,
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            operation="action",
            action_name=action,
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=auth_user_uuid,
            tenant_id=tenant_uuid,
            meta={"handler": handler_name},
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await emit_biz_trace_event(
            registry=registry,
            stage="error",
            source_plugin=resource.namespace,
            entity_set=entity_set,
            action_name=action,
            tenant_id=tenant_uuid,
            status_code=500,
            duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            details={
                "operation": "action",
                "handler": handler_name,
                "error": str(e),
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await commit_idempotency_failure(
            registry=registry,
            idempotency_state=idempotency_state,
            response_code=500,
            response_payload={"Error": "Action execution failed."},
            error_code="error",
            error_message=str(e),
        )
        abort(500)

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        operation="action",
        action_name=action,
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=auth_user_uuid,
        tenant_id=tenant_uuid,
        meta={"handler": handler_name},
        request_id=request_id,
        correlation_id=correlation_id,
    )

    response_code, response_payload = _action_response_parts(result)
    await emit_biz_trace_event(
        registry=registry,
        stage="finish",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        tenant_id=tenant_uuid,
        status_code=response_code,
        duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )
    await commit_idempotency_success(
        registry=registry,
        idempotency_state=idempotency_state,
        response_code=response_code,
        response_payload=response_payload,
    )

    return result


@api.post("core/acp/v1/<entity_set>/<entity_id>/$action/<action>")
@permission_required(action_kw="action")
async def dispatch_entity_action(
    entity_set: str,
    entity_id: str,
    action: str,
    auth_user: str,
    logger_provider=_logger_provider,
    registry_provider=_registry_provider,
    sandbox_enforcer_provider=_sandbox_enforcer_provider,
    **_,
) -> Any:
    """Dispatch an action for an EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    scope_mode = _tenant_scope_mode(registry=registry, edm_type_name=edm_type_name)
    if scope_mode == _SCOPE_REQUIRED:
        abort(400, "Entity set is tenant-scoped; use the tenant action endpoint.")

    svc = registry.get_edm_service(resource.service_key)

    handler_name = f"entity_action_{action}"
    handler = getattr(svc, handler_name, None)
    if handler is None or not callable(handler):
        abort(
            501,
            description=(
                f"Action {action!r} is declared for {entity_set!r} but service "
                f"{type(svc).__name__} does not implement {handler_name}()."
            ),
        )

    try:
        entity_uuid = uuid.UUID(entity_id)
    except ValueError:
        abort(400, "Invalid entity ID.")

    try:
        auth_user_uuid = uuid.UUID(str(auth_user))
    except ValueError as e:
        logger.error(e)
        abort(500)

    action_cap = resource.capabilities.actions.get(action)
    schema: IValidationBase = action_cap.get("schema")
    if schema is None:
        abort(501, "Data validation could not be performed.")

    try:
        action_data = schema.model_validate(data)
    except ValidationError as e:
        abort(400, str(e))

    tenant_for_capability = None
    if scope_mode == _SCOPE_OPTIONAL:
        tenant_for_capability = _optional_uuid(getattr(action_data, "tenant_id", None))

    await _enforce_required_capabilities(
        action_cap=action_cap,
        tenant_id=tenant_for_capability,
        plugin_key=resource.namespace,
        action=action,
        auth_user_uuid=auth_user_uuid,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        request_id=request_id,
        correlation_id=correlation_id,
        registry=registry,
        sandbox_enforcer_provider=sandbox_enforcer_provider,
    )

    await enforce_schema_bindings(
        registry=registry,
        tenant_id=None,
        resource_namespace=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        payload=data,
        binding_kind="action",
    )

    idempotency_state = await acquire_idempotency(
        registry=registry,
        tenant_id=None,
        entity_set=entity_set,
        action_name=action,
        payload=data,
    )
    replay_response = idempotency_state.get("replay_response")
    if replay_response is not None:
        return replay_response

    started_at = time.perf_counter()
    await emit_biz_trace_event(
        registry=registry,
        stage="start",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )

    try:
        result = await handler(
            entity_id=entity_uuid,
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="action",
            action_name=action,
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=auth_user_uuid,
            meta={"handler": handler_name},
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await emit_biz_trace_event(
            registry=registry,
            stage="error",
            source_plugin=resource.namespace,
            entity_set=entity_set,
            action_name=action,
            status_code=500,
            duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            details={
                "operation": "action",
                "handler": handler_name,
                "error": str(e),
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await commit_idempotency_failure(
            registry=registry,
            idempotency_state=idempotency_state,
            response_code=500,
            response_payload={"Error": "Action execution failed."},
            error_code="error",
            error_message=str(e),
        )
        abort(500)

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="action",
        action_name=action,
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=auth_user_uuid,
        meta={"handler": handler_name},
        request_id=request_id,
        correlation_id=correlation_id,
    )

    response_code, response_payload = _action_response_parts(result)
    await emit_biz_trace_event(
        registry=registry,
        stage="finish",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        status_code=response_code,
        duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )
    await commit_idempotency_success(
        registry=registry,
        idempotency_state=idempotency_state,
        response_code=response_code,
        response_payload=response_payload,
    )

    return result


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>/$action/<action>")
@permission_required(action_kw="action", tenant_kw="tenant_id")
async def dispatch_entity_action_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    action: str,
    auth_user: str,
    logger_provider=_logger_provider,
    registry_provider=_registry_provider,
    sandbox_enforcer_provider=_sandbox_enforcer_provider,
    **_,
) -> Any:
    """Dispatch a tenant-scoped action for an EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    scope_mode = _tenant_scope_mode(registry=registry, edm_type_name=edm_type_name)
    if scope_mode == _SCOPE_NONE:
        abort(400, "Entity set is not tenant-scoped.")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {tenant_id}.")

    try:
        entity_uuid = uuid.UUID(str(entity_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {entity_id}.")

    try:
        auth_user_uuid = uuid.UUID(str(auth_user))
    except ValueError as e:
        logger.error(e)
        abort(500)

    resource = registry.get_resource(entity_set)
    svc = registry.get_edm_service(resource.service_key)

    handler_name = f"action_{action}"
    handler = getattr(svc, handler_name, None)
    if handler is None or not callable(handler):
        abort(
            501,
            description=(
                f"Action {action!r} is declared for {entity_set!r} but service "
                f"{type(svc).__name__} does not implement {handler_name}()."
            ),
        )

    action_cap = resource.capabilities.actions.get(action)
    schema: IValidationBase = action_cap.get("schema")
    if schema is None:
        abort(501, "Data validation could not be performed.")

    try:
        action_data = schema.model_validate(data)
    except ValidationError as e:
        abort(400, str(e))

    await _enforce_required_capabilities(
        action_cap=action_cap,
        tenant_id=tenant_uuid,
        plugin_key=resource.namespace,
        action=action,
        auth_user_uuid=auth_user_uuid,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        request_id=request_id,
        correlation_id=correlation_id,
        registry=registry,
        sandbox_enforcer_provider=sandbox_enforcer_provider,
    )

    await enforce_schema_bindings(
        registry=registry,
        tenant_id=tenant_uuid,
        resource_namespace=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        payload=data,
        binding_kind="action",
    )

    idempotency_state = await acquire_idempotency(
        registry=registry,
        tenant_id=tenant_uuid,
        entity_set=entity_set,
        action_name=action,
        payload=data,
    )
    replay_response = idempotency_state.get("replay_response")
    if replay_response is not None:
        return replay_response

    started_at = time.perf_counter()
    await emit_biz_trace_event(
        registry=registry,
        stage="start",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        tenant_id=tenant_uuid,
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )

    where = {"tenant_id": tenant_uuid, "id": entity_uuid}

    try:
        result = await handler(
            tenant_id=tenant_uuid,
            entity_id=entity_uuid,
            where=where,
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="action",
            action_name=action,
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=auth_user_uuid,
            tenant_id=tenant_uuid,
            meta={"handler": handler_name},
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await emit_biz_trace_event(
            registry=registry,
            stage="error",
            source_plugin=resource.namespace,
            entity_set=entity_set,
            action_name=action,
            tenant_id=tenant_uuid,
            status_code=500,
            duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            details={
                "operation": "action",
                "handler": handler_name,
                "error": str(e),
            },
            request_id=request_id,
            correlation_id=correlation_id,
        )
        await commit_idempotency_failure(
            registry=registry,
            idempotency_state=idempotency_state,
            response_code=500,
            response_payload={"Error": "Action execution failed."},
            error_code="error",
            error_message=str(e),
        )
        abort(500)

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="action",
        action_name=action,
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=auth_user_uuid,
        tenant_id=tenant_uuid,
        meta={"handler": handler_name},
        request_id=request_id,
        correlation_id=correlation_id,
    )

    response_code, response_payload = _action_response_parts(result)
    await emit_biz_trace_event(
        registry=registry,
        stage="finish",
        source_plugin=resource.namespace,
        entity_set=entity_set,
        action_name=action,
        tenant_id=tenant_uuid,
        status_code=response_code,
        duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
        details={
            "operation": "action",
            "handler": handler_name,
        },
        request_id=request_id,
        correlation_id=correlation_id,
    )
    await commit_idempotency_success(
        registry=registry,
        idempotency_state=idempotency_state,
        response_code=response_code,
        response_payload=response_payload,
    )

    return result
