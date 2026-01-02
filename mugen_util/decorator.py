"""Defines decorators used for API endpoints."""

from functools import wraps
from types import SimpleNamespace


from quart import abort, current_app


def matrix_platform_required(
    config: SimpleNamespace = None,
):
    """Check that the Matrix platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                if "matrix" not in config.mugen.platforms:
                    current_app.logger.error("Matrix platform not enabled.")
                    abort(501)
                return await func(*args, **kwargs)
            except (AttributeError, KeyError):
                current_app.logger.error("Could not get platform configuration.")
                abort(500)

        return wrapper

    return decorator


def telnet_platform_required(
    config: SimpleNamespace = None,
):
    """Check that the Telnet platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                if "telnet" not in config.mugen.platforms:
                    current_app.logger.error("Telnet platform not enabled.")
                    abort(501)
                return await func(*args, **kwargs)
            except (AttributeError, KeyError):
                current_app.logger.error("Could not get platform configuration.")
                abort(500)

        return wrapper

    return decorator
