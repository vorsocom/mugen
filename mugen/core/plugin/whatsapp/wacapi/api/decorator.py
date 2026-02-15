"""
Provides webhook decorators for the WhatsApp Cloud API (WACAPI) endpoints.
"""

from functools import wraps
import hashlib
import hmac
import ipaddress
import os
from types import SimpleNamespace


from quart import abort, request

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def whatsapp_platform_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Check that the WhatsApp platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                if "whatsapp" not in config.mugen.platforms:
                    logger.error("WhatsApp platform not enabled.")
                    abort(501)
            except (AttributeError, KeyError):
                logger.error("Could not get platform configuration.")
                abort(500)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def whatsapp_request_signature_verification_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            try:
                app_secret = config.whatsapp.app.secret
            except (AttributeError, KeyError):
                logger.error("WhatsApp app secret not found.")
                abort(500)

            try:
                xhubsig = request.headers["X-Hub-Signature-256"].removeprefix("sha256=")
            except KeyError:
                logger.error("Could not get request hash.")
                abort(400)

            data = await request.get_data()

            hexdigest = hmac.new(
                app_secret.encode("utf8"),
                data,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(xhubsig, hexdigest):
                logger.error("API call unauthorized.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator


def whatsapp_server_ip_allow_list_required(
    _fn=None,
    *,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config: SimpleNamespace = config_provider()
            logger: ILoggingGateway = logger_provider()

            verification_required: bool
            try:
                verification_required = config.whatsapp.servers.verify_ip
            except (AttributeError, KeyError):
                logger.error("WhatsApp ip verification requirement unknown.")
                verification_required = None

            if verification_required is not True:
                return await func(*args, **kwargs)

            try:
                networks: list
                with open(
                    os.path.join(config.basedir, config.whatsapp.servers.allowed),
                    "r",
                    encoding="utf8",
                ) as f:
                    networks = [line.strip() for line in f if line.strip() != ""]
            except (AttributeError, FileNotFoundError, IsADirectoryError, KeyError):
                logger.error("WhatsApp servers allow list not found.")
                abort(500)

            remote_addr = None
            if hasattr(request, "access_route") and len(request.access_route) > 0:
                remote_addr = request.access_route[0]
            if remote_addr in [None, ""]:
                remote_addr = request.remote_addr
            if remote_addr in [None, ""]:
                remote_addr = request.headers.get("Remote-Addr")
            if remote_addr in [None, ""]:
                logger.error("Remote address could not be determined.")
                abort(400)

            try:
                remote_ip = ipaddress.ip_address(remote_addr)
            except ValueError:
                logger.error("Remote address is invalid.")
                abort(400)

            try:
                hits = [
                    network
                    for network in networks
                    if remote_ip in ipaddress.ip_network(network)
                ]
            except ValueError:
                logger.error("Invalid CIDR entry in WhatsApp allow list.")
                abort(500)

            if len(hits) == 0:
                logger.error("Remote address not in allow list.")
                abort(403)

            return await func(*args, **kwargs)

        return wrapper

    if _fn is not None and callable(_fn):
        return decorator(_fn)

    return decorator
