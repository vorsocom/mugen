"""
Provides webhook decorators for the WhatsApp Cloud API (WACAPI) endpoints.
"""

from functools import wraps
import hashlib
import hmac
import ipaddress
import json
import os
from types import SimpleNamespace


from quart import abort, request

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _client_profile_service() -> MessagingClientProfileService | None:
    relational_storage_gateway = getattr(
        di.container,
        "relational_storage_gateway",
        None,
    )
    if relational_storage_gateway is None:
        return None
    return MessagingClientProfileService(
        table="admin_messaging_client_profile",
        rsg=relational_storage_gateway,
    )


def _extract_phone_number_id(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    entries = payload.get("entry")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes")
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            if not isinstance(metadata, dict):
                continue
            phone_number_id = metadata.get("phone_number_id")
            if isinstance(phone_number_id, str) and phone_number_id.strip() != "":
                return phone_number_id.strip()
    return None


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
            service = _client_profile_service()
            if service is None:
                logger.error("WhatsApp app secret not found.")
                abort(500)

            path_token = kwargs.get("path_token")
            if not isinstance(path_token, str) or path_token.strip() == "":
                logger.error("WhatsApp webhook path token missing.")
                abort(400)

            try:
                client_profile = await service.resolve_active_by_identifier(
                    platform_key="whatsapp",
                    identifier_type="path_token",
                    identifier_value=path_token,
                )
            except (KeyError, RuntimeError, TypeError):
                logger.error("WhatsApp app secret not found.")
                abort(500)

            if client_profile is None:
                logger.error("WhatsApp webhook path token verification failed.")
                abort(401)

            data = await request.get_data()
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                logger.error("Could not parse WhatsApp webhook payload.")
                abort(400)

            phone_number_id = _extract_phone_number_id(payload)
            if phone_number_id is None:
                logger.error("WhatsApp phone_number_id missing from webhook payload.")
                abort(400)
            if str(client_profile.phone_number_id or "").strip() != phone_number_id:
                logger.error("WhatsApp phone_number_id verification failed.")
                abort(401)

            try:
                runtime_config = await service.build_runtime_config(
                    config=config,
                    client_profile=client_profile,
                )
                app_secret = str(runtime_config.whatsapp.app.secret)
            except (AttributeError, KeyError, RuntimeError, TypeError):
                logger.error("WhatsApp app secret not found.")
                abort(500)

            try:
                xhubsig = request.headers["X-Hub-Signature-256"].removeprefix("sha256=")
            except KeyError:
                logger.error("Could not get request hash.")
                abort(400)

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

            try:
                verification_required = config.whatsapp.servers.verify_ip
            except (AttributeError, KeyError):
                logger.error("WhatsApp IP verification configuration missing.")
                abort(500)

            if not isinstance(verification_required, bool):
                logger.error("WhatsApp IP verification configuration invalid.")
                abort(500)

            if verification_required is False:
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

            trust_forwarded_for = bool(
                getattr(config.whatsapp.servers, "trust_forwarded_for", False)
            )
            remote_addr = request.remote_addr
            if trust_forwarded_for:
                forwarded_for = request.headers.get("X-Forwarded-For")
                if isinstance(forwarded_for, str) and forwarded_for.strip() != "":
                    remote_addr = forwarded_for.split(",")[0].strip()
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
