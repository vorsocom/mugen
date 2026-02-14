"""Implements CRUD API endpoints for EDM entity sets."""

import uuid
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ValidationError
from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudService,
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.acp.api.audit import emit_audit_event
from mugen.core.plugin.acp.api.decorator.auth import permission_required
from mugen.core.plugin.acp.api.decorator.rgql import rgql_enabled
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.sdk.resource import SoftDeleteMode
from mugen.core.utility.string.case_conversion_helper import title_to_snake

# pylint: disable=too-many-arguments
# ylint: disable=too-many-positional-arguments
# pylint: disable=too-many-locals


def _parse_uuid_or_none(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


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


def _build_create_data(
    data: dict[str, Any],
    create_schema: Any,
    *,
    tenant_scoped: bool,
) -> dict[str, Any]:
    """Build create payload from tuple/list schemas or Pydantic schema classes."""
    if create_schema is None:
        return {}

    if isinstance(create_schema, type) and issubclass(create_schema, BaseModel):
        try:
            validated = create_schema.model_validate(data)
        except ValidationError as e:
            abort(400, str(e))

        create_data = validated.model_dump(by_alias=False, exclude_none=True)
        if tenant_scoped:
            create_data.pop("tenant_id", None)
        return create_data

    create_data: dict[str, Any] = {}
    for item in create_schema:
        if tenant_scoped and item == "TenantId":
            continue

        content = data.get(item)
        if content is None:
            abort(400, f"Expected data: {create_schema}")

        create_data[title_to_snake(item)] = content

    return create_data


@api.get("core/acp/v1/<entity_set>/<entity_id>")
@api.get("core/acp/v1/<entity_set>", defaults={"entity_id": None})
@permission_required(permission_type=":read")
@rgql_enabled
async def get_entities(
    entity_set: str,
    entity_id: str | None,
    edm_type_name: str,
    rgql: SimpleNamespace,
    logger_provider=lambda: di.container.logging_gateway,
    **_,
) -> dict:
    """Get EDM entities from the given entity set."""
    logger: ILoggingGateway = logger_provider()

    data: dict[str, Any] = {}

    if entity_id is None:
        data["@context"] = f"_#{entity_set}"

        if rgql.count is not None:
            data["@count"] = rgql.count

        data["value"] = rgql.values

    else:
        if not rgql.values:
            logger.debug(f"{edm_type_name} not found: {entity_id}")
            abort(404)

        data["@context"] = f"_#{entity_set}/$entity"
        for k, v in rgql.values[0].items():
            data[k] = v

    return data


@api.get("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>")
@api.get("core/acp/v1/tenants/<tenant_id>/<entity_set>", defaults={"entity_id": None})
@permission_required(permission_type=":read", tenant_kw="tenant_id")
@rgql_enabled(tenant_kw="tenant_id")
async def get_entities_tenant(
    entity_set: str,
    entity_id: str | None,
    edm_type_name: str,
    rgql: SimpleNamespace,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> dict:
    """Get EDM entities scoped to the given tenant."""
    logger: ILoggingGateway = logger_provider()
    registry: IAdminRegistry = registry_provider()

    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
        logger.debug(
            f"Tenant route used for non-tenant-scoped entity_set: {entity_set}"
        )
        abort(400, "Entity set is not tenant-scoped.")

    data: dict[str, Any] = {}

    if entity_id is None:
        data["@context"] = f"_#{entity_set}"

        if rgql.count is not None:
            data["@count"] = rgql.count

        data["value"] = rgql.values

    else:
        if not rgql.values:
            logger.debug(f"{edm_type_name} not found: {entity_id}")
            abort(404)

        data["@context"] = f"_#{entity_set}/$entity"
        for k, v in rgql.values[0].items():
            data[k] = v

    return data


@api.post("core/acp/v1/<entity_set>")
@permission_required(permission_type=":create")
async def create_entity(
    entity_set: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Create an EDM entity in the given entity set."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    create_data = _build_create_data(
        data,
        resource.crud.create_schema,
        tenant_scoped=False,
    )

    svc: ICrudService = registry.get_edm_service(resource.service_key)
    try:
        created = await svc.create(create_data)
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            operation="create",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(create_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=created.id,
        operation="create",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        changed_fields=list(create_data.keys()),
        after=created,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 201


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>")
@permission_required(permission_type=":create", tenant_kw="tenant_id")
async def create_entity_tenant(
    tenant_id: str,
    entity_set: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Create an EDM entity in the given entity set, scoped to the tenant."""
    logger: ILoggingGateway = logger_provider()
    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
        logger.debug(
            f"Tenant route used for non-tenant-scoped entity_set: {entity_set}"
        )
        abort(400, "Entity set is not tenant-scoped.")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {tenant_id}.")

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    if "TenantId" in data or "tenant_id" in data:
        raw = data.get("TenantId") or data.get("tenant_id")
        try:
            supplied = uuid.UUID(str(raw))
        except (ValueError, TypeError):
            abort(400, "Invalid TenantId.")
        if supplied != tenant_uuid:
            abort(400, "TenantId is server-controlled for this endpoint.")

    validation_data = dict(data)
    validation_data["TenantId"] = str(tenant_uuid)

    create_data = _build_create_data(
        validation_data,
        resource.crud.create_schema,
        tenant_scoped=True,
    )

    create_data["tenant_id"] = tenant_uuid

    svc: ICrudService = registry.get_edm_service(resource.service_key)
    try:
        created = await svc.create(create_data)
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            operation="create",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(create_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=created.id,
        operation="create",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        tenant_id=tenant_uuid,
        changed_fields=list(create_data.keys()),
        after=created,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 201


@api.patch("core/acp/v1/<entity_set>/<entity_id>")
@permission_required(permission_type=":update")
async def update_entity(
    entity_set: str,
    entity_id: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Update an EDM entity in the given entity set."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Update operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    update_data: dict[str, Any] = {}
    if resource.crud.update_schema is not None:
        for item in resource.crud.update_schema:
            content = data.get(item)
            if content is None:
                continue
            update_data[title_to_snake(item)] = content

    if not update_data:
        return "", 204

    try:
        entity_uuid = uuid.UUID(entity_id)
    except ValueError:
        abort(400, "Invalid entity ID.")

    where = {"id": entity_uuid}

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        before = await svc.get(where)
        updated = await svc.update_with_row_version(
            where,
            expected_row_version=row_version,
            changes=update_data,
        )
    except RowVersionConflict:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="update",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(update_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="update",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(update_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if updated is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="update",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(update_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Update not performed. No row matched.")

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="update",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        changed_fields=list(update_data.keys()),
        before=before,
        after=updated,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 204


@api.patch("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>")
@permission_required(permission_type=":update", tenant_kw="tenant_id")
async def update_entity_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Update an EDM entity scoped to the tenant."""
    logger: ILoggingGateway = logger_provider()
    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
        logger.debug(
            f"Tenant route used for non-tenant-scoped entity_set: {entity_set}"
        )
        abort(400, "Entity set is not tenant-scoped.")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {tenant_id}.")

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    if "TenantId" in data or "tenant_id" in data:
        abort(400, "TenantId is not mutable via this endpoint.")

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Update operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    update_data: dict[str, Any] = {}
    if resource.crud.update_schema is not None:
        for item in resource.crud.update_schema:
            if item == "TenantId":
                continue

            content = data.get(item)
            if content is None:
                continue
            update_data[title_to_snake(item)] = content

    if not update_data:
        return "", 204

    try:
        entity_uuid = uuid.UUID(str(entity_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {entity_id}.")

    where = {
        "tenant_id": tenant_uuid,
        "id": entity_uuid,
    }

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        before = await svc.get(where)
        updated = await svc.update_with_row_version(
            where,
            expected_row_version=row_version,
            changes=update_data,
        )
    except RowVersionConflict:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="update",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(update_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="update",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(update_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if updated is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="update",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(update_data.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Update not performed. No row matched.")

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="update",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        tenant_id=tenant_uuid,
        changed_fields=list(update_data.keys()),
        before=before,
        after=updated,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 204


@api.delete("core/acp/v1/<entity_set>/<entity_id>")
@permission_required(permission_type=":delete")
async def delete_entity(
    entity_set: str,
    entity_id: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Hard delete an EDM entity from the given entity set."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Delete operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    try:
        entity_uuid = uuid.UUID(entity_id)
    except ValueError:
        abort(400, "Invalid entity ID.")

    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        deleted = await svc.delete_with_row_version(
            {"id": entity_uuid},
            expected_row_version=row_version,
        )
    except RowVersionConflict:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="delete",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="delete",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if deleted is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="delete",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Delete not performed. No row matched.")

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="delete",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        before=deleted,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 204


@api.delete("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>")
@permission_required(permission_type=":delete", tenant_kw="tenant_id")
async def delete_entity_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Hard delete an EDM entity scoped to the tenant."""
    logger: ILoggingGateway = logger_provider()
    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
        logger.debug(
            f"Tenant route used for non-tenant-scoped entity_set: {entity_set}"
        )
        abort(400, "Entity set is not tenant-scoped.")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {tenant_id}.")

    try:
        entity_uuid = uuid.UUID(str(entity_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {entity_id}.")

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Delete operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        deleted = await svc.delete_with_row_version(
            {
                "tenant_id": tenant_uuid,
                "id": entity_uuid,
            },
            expected_row_version=row_version,
        )
    except RowVersionConflict:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="delete",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="delete",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if deleted is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="delete",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Delete not performed. No row matched.")

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="delete",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        tenant_id=tenant_uuid,
        before=deleted,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 204


@api.post("core/acp/v1/<entity_set>/<entity_id>/$restore")
@permission_required(permission_type=":update")
async def restore_entity(
    entity_set: str,
    entity_id: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Restore a soft-deleted EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Restore operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    try:
        entity_uuid = uuid.UUID(str(entity_id))
    except ValueError:
        abort(400, "Invalid entity ID.")

    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    policy = resource.behavior.soft_delete
    if (
        policy.mode == SoftDeleteMode.NONE
        or not policy.allow_restore
        or not policy.column
    ):
        abort(405, "Restore is not supported for this entity set.")

    deleted_column = title_to_snake(policy.column)
    restore_value: Any
    if policy.mode == SoftDeleteMode.TIMESTAMP:
        restore_value = None
    elif policy.mode == SoftDeleteMode.FLAG:
        restore_value = False
    else:
        abort(405, "Restore is not supported for this entity set.")

    where = {"id": entity_uuid}
    changes = {deleted_column: restore_value}

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)

    try:
        before = await svc.get(where)
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if before is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Restore not performed. No row matched.")

    deleted_value = getattr(before, deleted_column, None)
    if policy.mode == SoftDeleteMode.TIMESTAMP and deleted_value is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "Entity is not soft-deleted.")

    if policy.mode == SoftDeleteMode.FLAG and not bool(deleted_value):
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "Entity is not soft-deleted.")

    try:
        restored = await svc.update_with_row_version(
            where,
            expected_row_version=row_version,
            changes=changes,
        )
    except RowVersionConflict:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if restored is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Restore not performed. No row matched.")

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="restore",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        changed_fields=list(changes.keys()),
        before=before,
        after=restored,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 204


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>/$restore")
@permission_required(permission_type=":update", tenant_kw="tenant_id")
async def restore_entity_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    auth_user: str | None = None,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
) -> tuple[str, int]:
    """Restore a tenant-scoped soft-deleted EDM entity."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Restore operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {tenant_id}.")

    try:
        entity_uuid = uuid.UUID(str(entity_id))
    except ValueError:
        abort(400, f"Invalid UUID for path parameter: {entity_id}.")

    actor_id = _parse_uuid_or_none(auth_user)
    request_id, correlation_id = _request_ids()

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    entity = _entity_name(resource.edm_type_name)

    edm_type_name = resource.edm_type_name
    if registry.schema.get_type(edm_type_name).find_property("TenantId") is None:
        logger.debug(
            f"Tenant route used for non-tenant-scoped entity_set: {entity_set}"
        )
        abort(400, "Entity set is not tenant-scoped.")

    policy = resource.behavior.soft_delete
    if (
        policy.mode == SoftDeleteMode.NONE
        or not policy.allow_restore
        or not policy.column
    ):
        abort(405, "Restore is not supported for this entity set.")

    deleted_column = title_to_snake(policy.column)
    restore_value: Any
    if policy.mode == SoftDeleteMode.TIMESTAMP:
        restore_value = None
    elif policy.mode == SoftDeleteMode.FLAG:
        restore_value = False
    else:
        abort(405, "Restore is not supported for this entity set.")

    where = {
        "tenant_id": tenant_uuid,
        "id": entity_uuid,
    }
    changes = {deleted_column: restore_value}

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)

    try:
        before = await svc.get(where)
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if before is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Restore not performed. No row matched.")

    deleted_value = getattr(before, deleted_column, None)
    if policy.mode == SoftDeleteMode.TIMESTAMP and deleted_value is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "Entity is not soft-deleted.")

    if policy.mode == SoftDeleteMode.FLAG and not bool(deleted_value):
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "Entity is not soft-deleted.")

    try:
        restored = await svc.update_with_row_version(
            where,
            expected_row_version=row_version,
            changes=changes,
        )
    except RowVersionConflict:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="conflict",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="error",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(500)

    if restored is None:
        await emit_audit_event(
            registry=registry,
            entity_set=entity_set,
            entity=entity,
            entity_id=entity_uuid,
            operation="restore",
            outcome="not_found",
            source_plugin=resource.namespace,
            actor_id=actor_id,
            tenant_id=tenant_uuid,
            changed_fields=list(changes.keys()),
            before=before,
            request_id=request_id,
            correlation_id=correlation_id,
        )
        abort(404, "Restore not performed. No row matched.")

    await emit_audit_event(
        registry=registry,
        entity_set=entity_set,
        entity=entity,
        entity_id=entity_uuid,
        operation="restore",
        outcome="success",
        source_plugin=resource.namespace,
        actor_id=actor_id,
        tenant_id=tenant_uuid,
        changed_fields=list(changes.keys()),
        before=before,
        after=restored,
        request_id=request_id,
        correlation_id=correlation_id,
    )

    return "", 204
