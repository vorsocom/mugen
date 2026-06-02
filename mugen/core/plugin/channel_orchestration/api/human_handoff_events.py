"""Implements human handoff live event stream endpoints."""

from __future__ import annotations

import uuid

from quart import Response, abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.decorator.auth import global_auth_required
from mugen.core.plugin.acp.contract.service import IAuthorizationService
from mugen.core.plugin.channel_orchestration.human_handoff_auth import (
    HUMAN_HANDOFF_OPERATOR_PERMISSION,
)


def _logger_provider():
    return di.container.logging_gateway


def _auth_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_SVC_AUTH)


def _handoff_service_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_HUMAN_HANDOFF)


def _optional_uuid(value: object, *, field_name: str) -> uuid.UUID | None:
    if value in [None, ""]:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        abort(400, f"{field_name} must be a valid UUID.")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


@api.get("/core/acp/v1/tenants/<tenant_id>/HumanHandoffEvents/stream")
@global_auth_required
async def human_handoff_events_stream(
    tenant_id: str,
    auth_user: str,
    logger_provider=_logger_provider,
    auth_provider=_auth_provider,
    handoff_service_provider=_handoff_service_provider,
):
    """Stream tenant-scoped human handoff updates over SSE."""
    logger: ILoggingGateway = logger_provider()
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
        auth_user_uuid = uuid.UUID(str(auth_user))
    except ValueError:
        abort(400, "tenant_id and auth_user must be valid UUID values.")

    auth_svc: IAuthorizationService = auth_provider()
    permitted = await auth_svc.has_permission(
        user_id=auth_user_uuid,
        permission_object=HUMAN_HANDOFF_OPERATOR_PERMISSION,
        permission_type=HUMAN_HANDOFF_OPERATOR_PERMISSION,
        tenant_id=tenant_uuid,
    )
    if not permitted:
        abort(403)

    last_event_id = request.headers.get("Last-Event-ID")
    if not isinstance(last_event_id, str) or last_event_id.strip() == "":
        last_event_id = request.args.get("last_event_id")

    session_id = _optional_uuid(
        request.args.get("session_id"),
        field_name="session_id",
    )
    status = _optional_text(request.args.get("status"))

    service = handoff_service_provider()
    try:
        stream = await service.stream_handoff_events(
            tenant_id=tenant_uuid,
            last_event_id=last_event_id,
            session_id=session_id,
            status=status,
        )
    except SQLAlchemyError as exc:
        logger.error(exc)
        abort(500)
    except ValueError as exc:
        abort(400, str(exc))
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.error(f"Failed to open human handoff event stream: {exc}")
        abort(500)

    return Response(
        stream,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
