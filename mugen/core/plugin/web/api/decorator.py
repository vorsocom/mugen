"""Provides decorators for web platform API endpoints."""

__all__ = ["web_access_required", "web_platform_required"]

import uuid
from functools import wraps
from types import SimpleNamespace

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.contract.service import IAuthorizationService
from mugen.core.plugin.web.auth import WEB_PLATFORM_ACCESS_PERMISSION


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _auth_provider():
    return di.container.get_required_ext_service(di.EXT_SERVICE_ADMIN_SVC_AUTH)


def web_access_required(
    _fn=None,
    *,
    auth_provider=_auth_provider,
    logger_provider=_logger_provider,
):
    """Ensure the authenticated user has web platform access permission."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            logger: ILoggingGateway = logger_provider()
            auth_user = kwargs.get("auth_user")
            try:
                auth_user_uuid = uuid.UUID(str(auth_user))
            except (TypeError, ValueError):
                logger.error("Invalid auth_user for web platform access check.")
                abort(500)

            auth_svc: IAuthorizationService = auth_provider()
            try:
                permitted = await auth_svc.has_permission_for_any_tenant(
                    user_id=auth_user_uuid,
                    permission_object=WEB_PLATFORM_ACCESS_PERMISSION,
                    permission_type=WEB_PLATFORM_ACCESS_PERMISSION,
                    allow_global_admin=True,
                )
            except SQLAlchemyError as exc:
                logger.error(exc)
                abort(500)

            if not permitted:
                abort(403)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def web_platform_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Ensure the web platform is active before serving an endpoint."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                if "web" not in config.mugen.platforms:
                    logger.error("Web platform not enabled.")
                    abort(501)
            except (AttributeError, KeyError):
                logger.error("Could not get platform configuration.")
                abort(500)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator
