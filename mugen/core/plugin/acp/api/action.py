"""Implements action API endpoints for EDM entity sets."""

import uuid
from typing import Any

from pydantic import ValidationError
from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.decorator.auth import permission_required
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry

# pylint: disable=too-many-arguments
# ylint: disable=too-many-positional-arguments
# pylint: disable=too-many-locals


@api.post("core/acp/v1/<entity_set>/$action/<action>")
@permission_required(action_kw="action")
async def dispatch_entity_set_action(
    entity_set: str,
    action: str,
    auth_user: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> Any:
    """Dispatch an action for an EDM entity set."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is not None:
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

    try:
        return await handler(
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>/$action/<action>")
@permission_required(action_kw="action", tenant_kw="tenant_id")
async def dispatch_entity_set_action_tenant(
    tenant_id: str,
    entity_set: str,
    action: str,
    auth_user: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> Any:
    """Dispatch a tenant-scoped action for an EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
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

    where = {"tenant_id": tenant_uuid}

    try:
        return await handler(
            tenant_id=tenant_uuid,
            where=where,
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)


@api.post("core/acp/v1/<entity_set>/<entity_id>/$action/<action>")
@permission_required(action_kw="action")
async def dispatch_entity_action(
    entity_set: str,
    entity_id: str,
    action: str,
    auth_user: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> Any:
    """Dispatch an action for an EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is not None:
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

    try:
        return await handler(
            entity_id=entity_uuid,
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>/$action/<action>")
@permission_required(action_kw="action", tenant_kw="tenant_id")
async def dispatch_entity_action_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    action: str,
    auth_user: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> Any:
    """Dispatch a tenant-scoped action for an EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
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

    where = {"tenant_id": tenant_uuid, "id": entity_uuid}

    try:
        return await handler(
            tenant_id=tenant_uuid,
            entity_id=entity_uuid,
            where=where,
            auth_user_id=auth_user_uuid,
            data=action_data,
        )
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)
