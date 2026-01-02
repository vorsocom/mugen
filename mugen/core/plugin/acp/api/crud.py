"""Implements CRUD API endpoints for EDM entity sets."""

import uuid
from types import SimpleNamespace
from typing import Any

from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudService,
    ICrudServiceWithRowVersion,
)
from mugen.core.plugin.acp.api.decorator.auth import permission_required
from mugen.core.plugin.acp.api.decorator.rgql import rgql_enabled
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.utility.string.case_conversion_helper import title_to_snake

# pylint: disable=too-many-arguments
# ylint: disable=too-many-positional-arguments
# pylint: disable=too-many-locals


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
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
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
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> tuple[str, int]:
    """Create an EDM entity in the given entity set."""
    logger: ILoggingGateway = logger_provider()
    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

    create_data: dict[str, str] = {}
    if resource.crud.create_schema is not None:
        for item in resource.crud.create_schema:
            content = data.get(item)
            if content is None:
                abort(400, f"Expected data: {resource.crud.create_schema}")

            create_data[title_to_snake(item)] = content

    svc: ICrudService = registry.get_edm_service(resource.service_key)
    try:
        await svc.create(create_data)
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    return "", 201


@api.post("core/acp/v1/tenants/<tenant_id>/<entity_set>")
@permission_required(permission_type=":create", tenant_kw="tenant_id")
async def create_entity_tenant(
    tenant_id: str,
    entity_set: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> tuple[str, int]:
    """Create an EDM entity in the given entity set, scoped to the tenant."""
    logger: ILoggingGateway = logger_provider()
    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

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

    create_data: dict[str, Any] = {}
    if resource.crud.create_schema is not None:
        for item in resource.crud.create_schema:
            # TenantId is server-controlled on tenant routes.
            if item == "TenantId":
                continue

            content = data.get(item)
            if content is None:
                abort(400, f"Expected data: {resource.crud.create_schema}")

            create_data[title_to_snake(item)] = content

    # Enforce tenant scope (even if the client supplies TenantId).
    if "TenantId" in data or "tenant_id" in data:
        raw = data.get("TenantId") or data.get("tenant_id")
        try:
            supplied = uuid.UUID(str(raw))
        except (ValueError, TypeError):
            abort(400, "Invalid TenantId.")
        if supplied != tenant_uuid:
            abort(400, "TenantId is server-controlled for this endpoint.")

    create_data["tenant_id"] = tenant_uuid

    svc: ICrudService = registry.get_edm_service(resource.service_key)
    try:
        await svc.create(create_data)
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    return "", 201


@api.patch("core/acp/v1/<entity_set>/<entity_id>")
@permission_required(permission_type=":update")
async def update_entity(
    entity_set: str,
    entity_id: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
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

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

    update_data: dict[str, str] = {}
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

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        updated = await svc.update_with_row_version(
            {"id": entity_uuid},
            expected_row_version=row_version,
            changes=update_data,
        )
    except RowVersionConflict:
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if updated is None:
        abort(404, "Update not performed. No row matched.")

    return "", 204


@api.patch("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>")
@permission_required(permission_type=":update", tenant_kw="tenant_id")
async def update_entity_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> tuple[str, int]:
    """Update an EDM entity scoped to the tenant."""
    logger: ILoggingGateway = logger_provider()
    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

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

    # Prevent tenant reassignment via generic patch.
    if "TenantId" in data or "tenant_id" in data:
        abort(400, "TenantId is not mutable via this endpoint.")

    row_version = data.get("RowVersion")
    if row_version is None:
        abort(400, "Update operation requires RowVersion.")

    try:
        row_version = int(row_version)
    except (TypeError, ValueError):
        abort(400, f"RowVersion must be a valid integer. {row_version} given.")

    resource = registry.get_resource(entity_set)

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

    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        updated = await svc.update_with_row_version(
            {
                "tenant_id": tenant_uuid,
                "id": entity_uuid,
            },
            expected_row_version=row_version,
            changes=update_data,
        )
    except RowVersionConflict:
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if updated is None:
        abort(404, "Update not performed. No row matched.")

    return "", 204


@api.delete("core/acp/v1/<entity_set>/<entity_id>")
@permission_required(permission_type=":delete")
async def delete_entity(
    entity_set: str,
    entity_id: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
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

    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)
    svc: ICrudServiceWithRowVersion = registry.get_edm_service(resource.service_key)
    try:
        deleted = await svc.delete_with_row_version(
            {"id": entity_uuid},
            expected_row_version=row_version,
        )
    except RowVersionConflict:
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if deleted is None:
        abort(404, "Delete not performed. No row matched.")

    return "", 204


@api.delete("core/acp/v1/tenants/<tenant_id>/<entity_set>/<entity_id>")
@permission_required(permission_type=":delete", tenant_kw="tenant_id")
async def delete_entity_tenant(
    tenant_id: str,
    entity_set: str,
    entity_id: str,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
    **_,
) -> tuple[str, int]:
    """Hard delete an EDM entity scoped to the tenant."""
    logger: ILoggingGateway = logger_provider()
    registry: IAdminRegistry = registry_provider()
    resource = registry.get_resource(entity_set)

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
        abort(409, "RowVersion conflict. Refresh and retry.")
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if deleted is None:
        abort(404, "Delete not performed. No row matched.")

    return "", 204
