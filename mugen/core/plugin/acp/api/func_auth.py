"""Implements auth functional API endpoints."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from quart import abort, request
from sqlalchemy.exc import SQLAlchemyError

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.api.decorator.auth import global_auth_required
from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.contract.service import IRefreshTokenService, IUserService
from mugen.core.plugin.acp.contract.service.jwt import (
    IJwtService,
    JwtVerifyParams,
    JwtVerifyProfile,
)


@api.get("core/acp/v1/auth/.well-known/jwks.json")
async def jwks(
    jwt_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_SVC_JWT
    ),
):
    """Publish JWKS."""
    jwt_svc: IJwtService = jwt_provider()
    return jwt_svc.jwks(), 200


@api.post("core/acp/v1/auth/login")
async def user_login(  # pylint: disable=too-many-locals
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
    jwt_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_SVC_JWT
    ),
    registry_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
):
    """User login."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    jwt_svc: IJwtService = jwt_provider()
    registry: IAdminRegistry = registry_provider()

    rtoken_svc: IRefreshTokenService = registry.get_edm_service(
        f"{config.acp.namespace}:ACP.RefreshToken"
    )
    user_svc: IUserService = registry.get_edm_service(
        f"{config.acp.namespace}:ACP.User"
    )

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    username = data.get("Username")
    password = data.get("Password")
    if not username or not password:
        logger.debug("Request parameter(s) missing.")
        abort(400)

    try:
        user = await user_svc.get_expanded({"username": username})
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if user is None:
        logger.debug("User not found.")
        user_svc.verify_password_hash(config.acp.login_dummy_hash, password)
        abort(401)

    if user.locked_at is not None:
        logger.debug("User locked.")
        user_svc.verify_password_hash(config.acp.login_dummy_hash, password)
        abort(401)

    if not user_svc.verify_password_hash(user.password_hash, password):
        logger.debug("Password incorrect.")
        try:
            await user_svc.update(
                {"id": user.id},
                {"failed_login_count": user.failed_login_count + 1},
            )
        except SQLAlchemyError as e:
            logger.error(e)
            abort(500)
        abort(401)

    current_time = datetime.now(timezone.utc)

    access_jti = uuid.uuid4()
    access_token_expiry = current_time + timedelta(
        seconds=config.acp.login_access_expiry,
    )
    access_token = jwt_svc.sign(
        {
            "sub": str(user.id),
            "iat": int(current_time.timestamp()),
            "nbf": int(current_time.timestamp()),
            "exp": int(access_token_expiry.timestamp()),
            "iss": config.acp.jwt.issuer,
            "aud": config.acp.jwt.audience,
            "jti": str(access_jti),
            "type": "access",
            "token_version": user.token_version,
        },
    )

    refresh_jti = uuid.uuid4()
    refresh_token_expiry = current_time + timedelta(
        seconds=config.acp.login_refresh_expiry,
    )
    refresh_token = jwt_svc.sign(
        {
            "sub": str(user.id),
            "iat": int(current_time.timestamp()),
            "nbf": int(current_time.timestamp()),
            "exp": int(refresh_token_expiry.timestamp()),
            "iss": config.acp.jwt.issuer,
            "aud": config.acp.jwt.audience,
            "jti": str(refresh_jti),
            "type": "refresh",
            "token_version": user.token_version,
        },
    )

    try:
        await rtoken_svc.create(
            {
                "token_hash": rtoken_svc.generate_refresh_token_hash(refresh_token),
                "token_jti": refresh_jti,
                "expires_at": refresh_token_expiry,
                "user_id": user.id,
            }
        )
        await user_svc.update(
            {"id": user.id},
            {
                "last_login_at": current_time,
                "failed_login_count": 0,
            },
        )
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    return {
        "access_token": access_token,
        "access_token_issued": int(current_time.timestamp()),
        "access_token_expires": int(access_token_expiry.timestamp()),
        "refresh_token": refresh_token,
        "username": user.username,
        "user_id": str(user.id),
        "roles": [f"{r.namespace}:{r.name}" for r in user.global_roles],
    }, 200


@api.post("core/acp/v1/auth/logout")
@global_auth_required
async def user_logout(
    auth_user: str,
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
    jwt_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_SVC_JWT
    ),
    registry_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
    **_,
):
    """User logout."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    jwt_svc: IJwtService = jwt_provider()
    registry: IAdminRegistry = registry_provider()

    rtoken_svc: IRefreshTokenService = registry.get_edm_service(
        f"{config.acp.namespace}:ACP.RefreshToken"
    )

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    token = data.get("RefreshToken")
    if not token:
        logger.debug("Request parameter(s) missing.")
        return "", 204

    token_payload = None
    try:
        token_payload = jwt_svc.verify(
            token,
            params=JwtVerifyParams(
                verify_exp=False,
                profile=JwtVerifyProfile.REFRESH,
            ),
        )
    except InvalidTokenError:
        # Invalid. no-op.
        return "", 204

    if token_payload.get("sub") != auth_user:
        logger.error("Cannot logout another user.")
        abort(401)

    try:
        token_jti = uuid.UUID(str(token_payload.get("jti")))
    except (ValueError, TypeError):
        # Malformed jti; treat as invalid token and no-op.
        return "", 204

    try:
        await rtoken_svc.delete({"token_jti": token_jti})
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    return "", 204


# pylint: disable=too-many-locals
# pylint: disable=too-many-return-statements
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
@api.post("core/acp/v1/auth/refresh")
async def user_refresh_login(
    config_provider=lambda: di.container.config,
    logger_provider=lambda: di.container.logging_gateway,
    jwt_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_SVC_JWT
    ),
    registry_provider=lambda: di.container.get_required_ext_service(
        di.EXT_SERVICE_ADMIN_REGISTRY
    ),
):
    """Refresh access token."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    jwt_svc: IJwtService = jwt_provider()
    registry: IAdminRegistry = registry_provider()

    rtoken_svc: IRefreshTokenService = registry.get_edm_service(
        f"{config.acp.namespace}:ACP.RefreshToken"
    )
    user_svc: IUserService = registry.get_edm_service(
        f"{config.acp.namespace}:ACP.User"
    )

    data = await request.get_json()
    if not isinstance(data, dict):
        logger.debug("`data` is not a dict.")
        abort(400)

    token = data.get("RefreshToken")
    if not token:
        logger.debug("Request parameter(s) missing.")
        return "", 204

    try:
        token_payload = jwt_svc.verify(
            token,
            params=JwtVerifyParams(
                verify_exp=True,
                profile=JwtVerifyProfile.REFRESH,
            ),
        )
    except ExpiredSignatureError:
        # Expired. abort.
        logger.debug("Expired refresh token.")
        abort(401)
    except InvalidTokenError as exc:
        # Invalid. no-op.
        logger.debug(f"Invalid refresh token. {exc}")
        return "", 204

    jti = token_payload.get("jti")
    if not jti:
        logger.debug("Missing jti in refresh token.")
        return "", 204

    try:
        jti_uuid = uuid.UUID(str(jti))
    except (ValueError, TypeError):
        logger.debug("Malformed jti in refresh token.")
        return "", 204

    try:
        login_refresh_token = await rtoken_svc.get({"token_jti": jti_uuid})
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if login_refresh_token is None:
        logger.debug("Login refresh token not found.")
        return "", 204

    if not await rtoken_svc.verify_refresh_token_hash(
        login_refresh_token.token_hash,
        token,
        jti_uuid,
    ):
        logger.debug("Token hash verification failed.")
        return "", 204

    try:
        user = await user_svc.get_expanded({"id": login_refresh_token.user_id})
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    if user is None:
        logger.debug("User not found.")
        return "", 204

    if user.token_version != token_payload.get("token_version"):
        logger.debug("Invalid token version.")
        return "", 204

    if user.locked_at is not None:
        abort(403)

    current_time = datetime.now(timezone.utc)

    access_jti = uuid.uuid4()
    access_token_expiry = current_time + timedelta(
        seconds=config.acp.login_access_expiry,
    )
    access_token = jwt_svc.sign(
        {
            "sub": str(user.id),
            "iat": int(current_time.timestamp()),
            "nbf": int(current_time.timestamp()),
            "exp": int(access_token_expiry.timestamp()),
            "iss": config.acp.jwt.issuer,
            "aud": config.acp.jwt.audience,
            "jti": str(access_jti),
            "type": "access",
            "token_version": user.token_version,
        },
    )

    refresh_jti = uuid.uuid4()
    refresh_token_expiry = current_time + timedelta(
        seconds=config.acp.login_refresh_expiry,
    )
    refresh_token = jwt_svc.sign(
        {
            "sub": str(user.id),
            "iat": int(current_time.timestamp()),
            "nbf": int(current_time.timestamp()),
            "exp": int(refresh_token_expiry.timestamp()),
            "iss": config.acp.jwt.issuer,
            "aud": config.acp.jwt.audience,
            "jti": str(refresh_jti),
            "type": "refresh",
            "token_version": user.token_version,
        },
    )

    try:
        await rtoken_svc.create(
            {
                "token_hash": rtoken_svc.generate_refresh_token_hash(refresh_token),
                "token_jti": refresh_jti,
                "expires_at": refresh_token_expiry,
                "user_id": user.id,
            }
        )
        await rtoken_svc.delete({"token_jti": jti_uuid})
    except SQLAlchemyError as e:
        logger.error(e)
        abort(500)

    return {
        "access_token": access_token,
        "access_token_issued": int(current_time.timestamp()),
        "access_token_expires": int(access_token_expiry.timestamp()),
        "refresh_token": refresh_token,
        "username": user.username,
        "user_id": str(user.id),
        "roles": [f"{r.namespace}:{r.name}" for r in user.global_roles],
    }, 200
