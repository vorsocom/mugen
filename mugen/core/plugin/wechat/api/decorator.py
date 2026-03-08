"""Provides webhook decorators for WeChat endpoints."""

from functools import wraps
from types import SimpleNamespace

from quart import abort

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _client_profile_service() -> MessagingClientProfileService | None:
    relational_storage_gateway = getattr(
        di.container,
        "relational_storage_gateway",
        None,
    )
    if relational_storage_gateway is None:
        return None
    return MessagingClientProfileService(
        table="admin_messaging_client_profile",
        rsg=relational_storage_gateway,
    )


def wechat_platform_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Check that the WeChat platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                if "wechat" not in config.mugen.platforms:
                    logger.error("WeChat platform not enabled.")
                    abort(501)
            except (AttributeError, KeyError):
                logger.error("Could not get platform configuration.")
                abort(500)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def wechat_webhook_path_token_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Validate WeChat webhook path token from URL path."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            path_token = kwargs.get("path_token")
            if not isinstance(path_token, str) or path_token.strip() == "":
                logger.error("WeChat webhook path token missing.")
                abort(400)

            service = _client_profile_service()
            if service is None:
                logger.error("WeChat webhook path token configuration missing.")
                abort(500)

            try:
                client_profile = await service.resolve_active_by_identifier(
                    platform_key="wechat",
                    identifier_type="path_token",
                    identifier_value=path_token,
                )
            except (KeyError, RuntimeError, TypeError):
                logger.error("WeChat webhook path token configuration missing.")
                abort(500)

            if client_profile is None:
                logger.error("WeChat webhook path token verification failed.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def wechat_provider_required(
    provider: str,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Validate configured active WeChat provider for endpoint."""

    normalized_provider = str(provider or "").strip().lower()

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()
            service = _client_profile_service()
            if service is None:
                logger.error("WeChat provider configuration missing.")
                abort(500)

            path_token = kwargs.get("path_token")
            if not isinstance(path_token, str) or path_token.strip() == "":
                logger.error("WeChat webhook path token missing.")
                abort(400)

            try:
                client_profile = await service.resolve_active_by_identifier(
                    platform_key="wechat",
                    identifier_type="path_token",
                    identifier_value=path_token,
                )
                if client_profile is None:
                    logger.error("WeChat webhook path token verification failed.")
                    abort(401)
                runtime_config = await service.build_runtime_config(
                    config=config,
                    client_profile=client_profile,
                )
                configured_provider = str(runtime_config.wechat.provider).strip().lower()
            except (AttributeError, KeyError, RuntimeError, TypeError):
                logger.error("WeChat provider configuration missing.")
                abort(500)

            if configured_provider != normalized_provider:
                logger.error(
                    "WeChat provider not enabled for endpoint "
                    f"configured={configured_provider} expected={normalized_provider}."
                )
                abort(501)

            return await func(*args, **kwargs)

        return wrapper

    return decorator
