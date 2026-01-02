"""Defines utility decorators for admin API endpoints."""

__all__ = ["global_admin_required", "global_auth_required", "permission_required"]

import uuid
from functools import wraps
from types import SimpleNamespace

from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import IAuthorizationService, IUserService
from mugen.core.plugin.acp.contract.service.jwt import (
    IJwtService,
    JwtVerifyParams,
    JwtVerifyProfile,
)


def global_admin_required(
    _fn=None,
    *,
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
):
    """Check that the client has administrator privilege."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            token = _decode_access_token()
            user = await _require_user_from_token(token, expanded=True)

            global_roles = [
                f"{r.namespace}:{r.name}" for r in (user.global_roles or [])
            ]

            if f"{config.acp.namespace}:administrator" not in global_roles:
                logger.debug("Unauthorized request. User is not an administrator.")
                abort(403)

            kwargs["auth_user"] = str(user.id)
            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def global_auth_required(_fn=None):
    """Check that the client has authorization to call the endpoint."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            token = _decode_access_token()
            user = await _require_user_from_token(token, expanded=False)

            kwargs["auth_user"] = str(user.id)
            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def permission_required(  # pylint: disable=too-many-arguments
    *,
    permission_type: str | None = None,
    action_kw: str | None = None,
    tenant_kw: str | None = None,
    allow_global_admin: bool = False,
    auth_provider=lambda: di.container.get_ext_service("admin_svc_auth"),
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
):
    """Check that the client has the required permission."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()
            registry: IAdminRegistry = registry_provider()

            entity_set: str = kwargs.get("entity_set")

            if entity_set is None:
                abort(404)

            if entity_set not in registry.schema_index:
                abort(404)

            token = _decode_access_token()

            user = await _require_user_from_token(token, expanded=True)

            global_roles = [
                f"{r.namespace}:{r.name}" for r in (user.global_roles or [])
            ]

            is_admin = f"{config.acp.namespace}:administrator" in global_roles

            resource = registry.get_resource(entity_set)

            if permission_type:
                if ":" not in permission_type:
                    logger.error("Invalid permission type (missing colon).")
                    abort(500, "Server misconfiguration: invalid permission_type.")

                op = permission_type.split(":", 1)[-1]
                if not resource.capabilities.op_allowed(op):
                    abort(405, "Action not permitted.")

            perm_type = None
            if action_kw:
                action = kwargs.get(action_kw)
                if action is None:
                    abort(400, f"Missing required path parameter: {action_kw}")

                action_cap = resource.capabilities.actions.get(action)
                if action_cap is None:
                    abort(405, "Action not defined.")

                perm_type = action_cap.get("perm")
                if perm_type is None:
                    abort(405, "Action not permitted.")

                if perm_type == "":
                    perm_type = resource.permissions.manage

                is_admin_action = action_cap.get("is_admin_action")
                if is_admin_action and not is_admin:
                    abort(403, "Action requires administrator privilege.")

            if not (is_admin and allow_global_admin):
                tenant_id = None
                if tenant_kw:
                    raw = kwargs.get(tenant_kw)
                    if raw is None:
                        abort(400, f"Missing required path parameter: {tenant_kw}.")

                    try:
                        tenant_id = uuid.UUID(str(raw))
                    except ValueError:
                        abort(400, f"Invalid UUID for path parameter: {tenant_kw}.")

                auth_svc: IAuthorizationService = auth_provider()
                ok = await auth_svc.has_permission(
                    user_id=user.id,
                    permission_object=resource.perm_obj,
                    permission_type=permission_type or perm_type,
                    tenant_id=tenant_id,
                    allow_global_admin=allow_global_admin,
                )
                if not ok:
                    abort(403)

            kwargs["allow_global_admin"] = allow_global_admin
            kwargs["auth_user"] = str(user.id)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def _get_bearer_token_from_header(
    logger_provider=lambda: di.container.logging_gateway,
) -> str:
    """Extract the bearer token from the Authorization header."""
    logger: ILoggingGateway = logger_provider()
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        logger.debug("Authorization header missing.")
        abort(401)

    parts = auth_header.split()

    # Expect: "Bearer <token>"
    if len(parts) != 2 or parts[0].lower() != "bearer":
        logger.debug("Invalid authorization header format.")
        abort(401)

    return parts[1]


def _decode_access_token(
    logger_provider=lambda: di.container.logging_gateway,
    jwt_provider=lambda: di.container.get_ext_service("admin_svc_jwt"),
) -> dict:
    logger: ILoggingGateway = logger_provider()
    jwt_svc: IJwtService = jwt_provider()
    bearer_token = _get_bearer_token_from_header()
    try:
        token = jwt_svc.verify(
            bearer_token,
            params=JwtVerifyParams(
                verify_exp=True,
                profile=JwtVerifyProfile.ACCESS,
            ),
        )
    except ExpiredSignatureError:
        logger.debug("Unauthorized request. Token expired.")
        abort(401)
    except InvalidTokenError:
        logger.debug("Unauthorized request. Invalid token.")
        abort(401)

    user_id = token.get("sub")
    try:
        uuid.UUID(str(user_id))
    except TypeError:
        logger.error("Invalid token subject type.")
        abort(401)
    except ValueError:
        logger.debug("Invalid token subject.")
        abort(401)

    return token


async def _require_user_from_token(
    token: dict,
    *,
    expanded: bool = False,
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
    registry_provider=lambda: di.container.get_ext_service("admin_registry"),
):
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    registry: IAdminRegistry = registry_provider()

    user_svc: IUserService = registry.get_edm_service(
        f"{config.acp.namespace}:ACP.User"
    )

    user_id = token["sub"]
    try:
        if expanded:
            user = await user_svc.get_expanded({"id": uuid.UUID(user_id)})
        else:
            user = await user_svc.get({"id": uuid.UUID(user_id)})
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if user is None:
        logger.debug("Unauthorized request. User not found.")
        abort(401)

    if user.deleted_at is not None:
        logger.debug("Unauthorized request. User deleted.")
        abort(401)

    if user.locked_at is not None:
        logger.debug("Unauthorized request. User locked.")
        abort(401)

    if user.token_version != token.get("token_version"):
        logger.debug("Unauthorized request. Invalid token version.")
        abort(401)

    return user
