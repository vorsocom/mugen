"""Implements WhatsApp Flow Data endpoints for WACAPI."""

import hashlib
import hmac
import json
from types import SimpleNamespace
from typing import Any

from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.plugin.acp.service.messaging_client_profile import (
    MessagingClientProfileService,
)
from mugen.core.plugin.whatsapp.wacapi.api.decorator import (
    whatsapp_platform_required,
    whatsapp_server_ip_allow_list_required,
)
from mugen.core.plugin.whatsapp.wacapi.flow_data import (
    WhatsAppFlowDataCryptoError,
    WhatsAppFlowDataInvalidTokenError,
    WhatsAppFlowDataNoHandlerError,
    WhatsAppFlowDataRegistry,
    WhatsAppFlowDataRequest,
    decrypt_flow_data_request,
    encrypt_flow_data_response,
)


def _config_provider():
    return di.container.config


def _logger_provider():
    return di.container.logging_gateway


def _flow_data_registry_provider() -> WhatsAppFlowDataRegistry | None:
    return di.container.get_ext_service(
        di.EXT_SERVICE_WHATSAPP_FLOW_DATA_REGISTRY,
        None,
    )


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


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_path(root: object, *path: str) -> object:
    cursor = root
    for token in path:
        cursor = getattr(cursor, token, None)
        if cursor is None:
            return None
    return cursor


def _verify_request_signature(
    *,
    app_secret: str,
    raw_body: bytes,
    logger: ILoggingGateway,
) -> bool:
    try:
        signature_header = request.headers["X-Hub-Signature-256"]
    except KeyError:
        logger.error("Could not get WhatsApp Flow Data request hash.")
        return False

    signature = signature_header.removeprefix("sha256=")
    hexdigest = hmac.new(
        app_secret.encode("utf8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, hexdigest):
        logger.error("WhatsApp Flow Data request unauthorized.")
        return False
    return True


def _extract_flow_name(payload: dict[str, Any], data: dict[str, Any]) -> str | None:
    return _normalize_optional_text(
        data.get("flow_name"),
    ) or _normalize_optional_text(payload.get("flow_name"))


def _flow_error(status_code: int, payload: dict[str, Any] | None = None):
    if payload is None:
        return "", status_code
    return payload, status_code


@api.post("/whatsapp/wacapi/flow-data/<path_token>")
@whatsapp_platform_required
@whatsapp_server_ip_allow_list_required
async def whatsapp_wacapi_flow_data(
    path_token: str,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
    client_profile_service_provider=None,
    flow_data_registry_provider=_flow_data_registry_provider,
):
    """Respond to encrypted WhatsApp Flow Data callbacks."""
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()
    if client_profile_service_provider is None:
        client_profile_service_provider = _client_profile_service

    service = (
        client_profile_service_provider()
        if callable(client_profile_service_provider)
        else None
    )
    if service is None:
        logger.error("Could not get WhatsApp Flow Data client profile service.")
        abort(500)

    if not isinstance(path_token, str) or path_token.strip() == "":
        logger.error("WhatsApp Flow Data path token missing.")
        abort(400)

    try:
        client_profile = await service.resolve_active_by_identifier(
            platform_key="whatsapp",
            identifier_type="path_token",
            identifier_value=path_token,
        )
        if client_profile is None:
            logger.error("WhatsApp Flow Data path token verification failed.")
            abort(401)
        runtime_config = await service.build_runtime_config(
            config=config,
            client_profile=client_profile,
        )
    except (AttributeError, KeyError, RuntimeError, TypeError):
        logger.error("Could not resolve WhatsApp Flow Data client profile.")
        abort(500)

    raw_body = await request.get_data()
    app_secret = _normalize_optional_text(
        _read_path(runtime_config, "whatsapp", "app", "secret")
    )
    if app_secret is None:
        logger.error("WhatsApp Flow Data app secret not found.")
        abort(500)
    if not _verify_request_signature(
        app_secret=app_secret,
        raw_body=raw_body,
        logger=logger,
    ):
        return _flow_error(432)

    try:
        encrypted_payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        logger.error("Could not parse WhatsApp Flow Data request payload.")
        return _flow_error(421)
    if not isinstance(encrypted_payload, dict):
        logger.error("WhatsApp Flow Data request payload is not a JSON object.")
        return _flow_error(421)

    private_key = _normalize_optional_text(
        _read_path(runtime_config, "whatsapp", "flows", "private_key")
    )
    private_key_passphrase = _normalize_optional_text(
        _read_path(runtime_config, "whatsapp", "flows", "private_key_passphrase")
    )
    if private_key is None:
        logger.error("WhatsApp Flow Data private key not found.")
        return _flow_error(421)

    try:
        decrypted_payload, crypto_material = decrypt_flow_data_request(
            encrypted_payload,
            private_key_pem=private_key,
            private_key_passphrase=private_key_passphrase,
        )
    except WhatsAppFlowDataCryptoError as exc:
        logger.error(f"WhatsApp Flow Data request decrypt failed: {exc}")
        return _flow_error(421)

    data = decrypted_payload.get("data")
    if not isinstance(data, dict):
        data = {}

    registry = (
        flow_data_registry_provider()
        if callable(flow_data_registry_provider)
        else None
    )
    if registry is None:
        logger.error("WhatsApp Flow Data registry not found.")
        abort(500)

    request_context = WhatsAppFlowDataRequest(
        tenant_id=getattr(client_profile, "tenant_id", None),
        client_profile_id=getattr(client_profile, "id", None),
        client_profile_key=_normalize_optional_text(
            getattr(client_profile, "profile_key", None)
        ),
        phone_number_id=_normalize_optional_text(
            getattr(client_profile, "phone_number_id", None)
        ),
        path_token=path_token,
        runtime_config=runtime_config,
        flow_token=_normalize_optional_text(decrypted_payload.get("flow_token")),
        flow_name=_extract_flow_name(decrypted_payload, data),
        action=_normalize_optional_text(decrypted_payload.get("action")),
        screen=_normalize_optional_text(decrypted_payload.get("screen")),
        data=data,
        raw_payload=decrypted_payload,
    )

    try:
        response_payload = await registry.handle_flow_data(request_context)
        encrypted_response = encrypt_flow_data_response(
            response_payload,
            crypto_material=crypto_material,
        )
    except WhatsAppFlowDataInvalidTokenError as exc:
        return _flow_error(427, {"error_msg": exc.error_msg})
    except WhatsAppFlowDataNoHandlerError as exc:
        logger.error(str(exc))
        abort(500)
    except WhatsAppFlowDataCryptoError as exc:
        logger.error(f"WhatsApp Flow Data response encrypt failed: {exc}")
        abort(500)

    return encrypted_response
