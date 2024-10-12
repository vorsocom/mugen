"""Defines decorators used for API endpoints."""

from functools import wraps
import hashlib
import hmac
import ipaddress
import os


from quart import abort, current_app, request


def matrix_platform_required(arg=None):
    """Check that the Matrix platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            try:
                if "matrix" not in current_app.config["ENV"].mugen.platforms():
                    current_app.logger.error("Matrix platform not enabled.")
                    abort(501)
                return await func(*args, **kwargs)
            except (AttributeError, KeyError):
                current_app.logger.error("Could not get platform configuration.")
                abort(500)

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator


def telnet_platform_required(arg=None):
    """Check that the Telnet platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            try:
                if "telnet" not in current_app.config["ENV"].mugen.platforms():
                    current_app.logger.error("Telnet platform not enabled.")
                    abort(501)
                return await func(*args, **kwargs)
            except (AttributeError, KeyError):
                current_app.logger.error("Could not get platform configuration.")
                abort(500)

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator


def whatsapp_platform_required(arg=None):
    """Check that the WhatsApp platform is enabled."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            try:
                if "whatsapp" not in current_app.config["ENV"].mugen.platforms():
                    current_app.logger.error("WhatsApp platform not enabled.")
                    abort(501)
                return await func(*args, **kwargs)
            except (AttributeError, KeyError):
                current_app.logger.error("Could not get platform configuration.")
                abort(500)

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator


def whatsapp_server_ip_allow_list_required(arg=None):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            try:
                allow_list_path = current_app.config["ENV"].whatsapp.servers.allowed()
                basedir = current_app.config["BASEDIR"]
                networks: list
                with open(
                    f"{basedir}{os.sep}{allow_list_path}", "r", encoding="utf8"
                ) as f:
                    networks = [l.rstrip() for l in f]
            except (AttributeError, FileNotFoundError, IsADirectoryError, KeyError):
                current_app.logger.error("WhatsApp servers allow list not found.")
                abort(500)

            verification_required: str
            try:
                verification_required = current_app.config[
                    "ENV"
                ].whatsapp.servers.verify_ip()
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

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator


def whatsapp_request_signature_verification_required(arg=None):
    """Authenticate requests to the webhook using app secret."""

    def decorator(func):
        @wraps(func)
        async def decorated(*args, **kwargs):
            try:
                app_secret = current_app.config["ENV"].whatsapp.app.secret()
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
                abort(401)

            return await func(*args, **kwargs)

        return decorated

    if callable(arg):
        return decorator(arg)
    return decorator
