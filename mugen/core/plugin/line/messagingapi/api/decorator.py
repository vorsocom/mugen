"""Provides webhook decorators for LINE Messaging API endpoints."""

from __future__ import annotations

import base64
from functools import wraps
import hashlib
import hmac
from types import SimpleNamespace

from quart import abort, request

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def line_platform_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Check that the LINE platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                if "line" not in config.mugen.platforms:
                    logger.error("LINE platform not enabled.")
                    abort(501)
            except (AttributeError, KeyError):
                logger.error("Could not get platform configuration.")
                abort(500)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def line_webhook_path_token_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Validate LINE webhook path token from URL path."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            path_token = kwargs.get("path_token")
            if not isinstance(path_token, str) or path_token.strip() == "":
                logger.error("LINE webhook path token missing.")
                abort(400)

            try:
                expected_token = str(config.line.webhook.path_token)
            except (AttributeError, KeyError):
                logger.error("LINE webhook path token configuration missing.")
                abort(500)

            if hmac.compare_digest(path_token.strip(), expected_token.strip()) is not True:
                logger.error("LINE webhook path token verification failed.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def line_webhook_signature_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Validate LINE webhook signature header against request body."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                channel_secret = str(config.line.channel.secret)
            except (AttributeError, KeyError):
                logger.error("LINE channel secret configuration missing.")
                abort(500)

            supplied_signature = request.headers.get("X-Line-Signature")
            if not isinstance(supplied_signature, str) or supplied_signature.strip() == "":
                logger.error("LINE webhook signature header missing.")
                abort(401)

            payload = await request.get_data()
            expected_signature = base64.b64encode(
                hmac.new(
                    channel_secret.encode("utf-8"),
                    payload,
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            if hmac.compare_digest(supplied_signature.strip(), expected_signature) is not True:
                logger.error("LINE webhook signature verification failed.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator
