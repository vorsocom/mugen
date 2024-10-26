"""Defines decorators used for API endpoints."""

from functools import wraps
import hashlib
import hmac
import ipaddress
import os
from types import SimpleNamespace


from quart import abort, current_app, request


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


def whatsapp_platform_required(
    config: SimpleNamespace = None,
):
    """Check that the WhatsApp platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                if "whatsapp" not in config.mugen.platforms:
                    current_app.logger.error("WhatsApp platform not enabled.")
                    abort(501)
                return await func(*args, **kwargs)
            except (AttributeError, KeyError):
                current_app.logger.error("Could not get platform configuration.")
                abort(500)

        return wrapper

    return decorator


def whatsapp_request_signature_verification_required(
    config: SimpleNamespace = None,
):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                app_secret = config.whatsapp.app.secret
            except (AttributeError, KeyError):
                current_app.logger.error("WhatsApp app secret not found.")
                abort(500)

            try:
                xhubsig = request.headers["X-Hub-Signature-256"].removeprefix("sha256=")
            except KeyError:
                current_app.logger.error("Could not get request hash.")
                abort(400)

            data = await request.get_data()

            hexdigest = hmac.new(
                app_secret.encode("utf8"),
                data,
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(xhubsig, hexdigest):
                current_app.logger.error("API call unauthorized.")
                abort(401)

            return await func(*args, **kwargs)

        return wrapper

    return decorator


def whatsapp_server_ip_allow_list_required(
    config: SimpleNamespace = None,
):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                networks: list
                with open(
                    os.path.join(config.basedir, config.whatsapp.servers.allowed),
                    "r",
                    encoding="utf8",
                ) as f:
                    networks = [l.rstrip() for l in f]
            except (AttributeError, FileNotFoundError, IsADirectoryError, KeyError):
                current_app.logger.error("WhatsApp servers allow list not found.")
                abort(500)

            verification_required: str
            try:
                verification_required = config.whatsapp.servers.verify_ip
            except (AttributeError, KeyError):
                current_app.logger.error(
                    "WhatsApp ip verification requirement unknown."
                )
                verification_required = None

            if verification_required is True:
                remote_addr = request.headers["Remote-Addr"]
                hits = [
                    x
                    for x in networks
                    if ipaddress.ip_address(remote_addr) in ipaddress.ip_network(x)
                ]

                if len(hits) == 0:
                    current_app.logger.error("Remote address not in allow list.")
                    abort(500)

            return await func(*args, **kwargs)

        return wrapper

    return decorator
