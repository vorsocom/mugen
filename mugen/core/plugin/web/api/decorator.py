"""Provides decorators for web platform API endpoints."""

__all__ = ["web_platform_required"]

from functools import wraps
from types import SimpleNamespace

from quart import abort

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


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
