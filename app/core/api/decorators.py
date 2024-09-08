"""Defines decorators used for API endpoints."""

from functools import wraps
import json


from quart import abort, current_app


def matrix_platform_required(arg=None):
    """Check that the Matrix platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            if "matrix" not in json.loads(
                current_app.config["ENV"]["gloria_platforms"]
            ):
                abort(501)
            return await func(*args, **kwargs)

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator


def whatsapp_platform_required(arg=None):
    """Check that the WhatsApp platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            if "whatsapp" not in json.loads(
                current_app.config["ENV"]["gloria_platforms"]
            ):
                abort(501)
            return await func(*args, **kwargs)

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator
