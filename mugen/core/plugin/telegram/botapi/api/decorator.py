"""Provides webhook decorators for the Telegram Bot API endpoints."""

from functools import wraps
import hmac
from types import SimpleNamespace

from quart import abort, request

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def telegram_platform_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Check that the Telegram platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                if "telegram" not in config.mugen.platforms:
                    logger.error("Telegram platform not enabled.")
                    abort(501)
            except (AttributeError, KeyError):
                logger.error("Could not get platform configuration.")
                abort(500)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def telegram_webhook_path_token_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Validate Telegram webhook path token from URL path."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            path_token = kwargs.get("path_token")
            if not isinstance(path_token, str) or path_token.strip() == "":
                logger.error("Telegram webhook path token missing.")
                abort(400)

            try:
                expected_path_token = str(config.telegram.webhook.path_token).strip()
            except (AttributeError, KeyError):
                logger.error("Telegram webhook path token configuration missing.")
                abort(500)

            if expected_path_token == "":
                logger.error("Telegram webhook path token configuration missing.")
                abort(500)

            if hmac.compare_digest(path_token.strip(), expected_path_token) is not True:
                logger.error("Telegram webhook path token verification failed.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def telegram_webhook_secret_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Validate Telegram secret header for webhook calls."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                expected_secret = str(config.telegram.webhook.secret_token)
            except (AttributeError, KeyError):
                logger.error("Telegram webhook secret configuration missing.")
                abort(500)

            supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if not isinstance(supplied_secret, str) or supplied_secret.strip() == "":
                logger.error("Telegram webhook secret header missing.")
                abort(401)

            if (
                hmac.compare_digest(supplied_secret.strip(), expected_secret.strip())
                is not True
            ):
                logger.error("Telegram webhook secret verification failed.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator
