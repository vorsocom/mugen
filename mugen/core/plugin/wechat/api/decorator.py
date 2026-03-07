"""Provides webhook decorators for WeChat endpoints."""

from functools import wraps
import hmac
from types import SimpleNamespace

from quart import abort

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.utility.platform_runtime_profile import (
    find_platform_runtime_profile_key,
    get_platform_profile_section,
    get_platform_runtime_profile_keys,
    identifier_configured_for_platform,
)


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


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

            try:
                identifier_configured = identifier_configured_for_platform(
                    config,
                    platform="wechat",
                    identifier_type="path_token",
                )
                runtime_profile_key = find_platform_runtime_profile_key(
                    config,
                    platform="wechat",
                    identifier_type="path_token",
                    identifier_value=path_token,
                )
            except RuntimeError:
                logger.error("WeChat webhook path token configuration missing.")
                abort(500)

            if identifier_configured is not True:
                logger.error("WeChat webhook path token configuration missing.")
                abort(500)

            if runtime_profile_key is None:
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

            try:
                identifier_configured = identifier_configured_for_platform(
                    config,
                    platform="wechat",
                    identifier_type="path_token",
                )
            except RuntimeError:
                logger.error("WeChat provider configuration missing.")
                abort(500)

            if identifier_configured is not True:
                logger.error("WeChat provider configuration missing.")
                abort(500)

            profile_keys = get_platform_runtime_profile_keys(
                config,
                platform="wechat",
            )
            path_token = kwargs.get("path_token")
            runtime_profile_key = None
            if not isinstance(path_token, str) or path_token.strip() == "":
                if len(profile_keys) == 1:
                    runtime_profile_key = profile_keys[0]
                else:
                    logger.error("WeChat webhook path token missing.")
                    abort(400)

            try:
                if runtime_profile_key is None:
                    runtime_profile_key = find_platform_runtime_profile_key(
                        config,
                        platform="wechat",
                        identifier_type="path_token",
                        identifier_value=path_token,
                    )
                if runtime_profile_key is None:
                    logger.error("WeChat webhook path token verification failed.")
                    abort(401)
                profile_cfg = get_platform_profile_section(
                    config,
                    platform="wechat",
                    runtime_profile_key=runtime_profile_key,
                )
                configured_provider = str(profile_cfg.provider).strip().lower()
            except (AttributeError, KeyError, RuntimeError):
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
