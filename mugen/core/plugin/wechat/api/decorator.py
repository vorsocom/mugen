"""Provides webhook decorators for WeChat endpoints."""

from functools import wraps
import hmac
from types import SimpleNamespace

from quart import abort

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway


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
                expected_token = str(config.wechat.webhook.path_token)
            except (AttributeError, KeyError):
                logger.error("WeChat webhook path token configuration missing.")
                abort(500)

            if hmac.compare_digest(path_token.strip(), expected_token.strip()) is not True:
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
                configured_provider = str(config.wechat.provider).strip().lower()
            except (AttributeError, KeyError):
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
