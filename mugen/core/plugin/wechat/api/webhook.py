"""Implements webhook endpoints for WeChat Official Account and WeCom."""

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import struct
from types import SimpleNamespace
from xml.etree import ElementTree

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from quart import abort, request

from mugen.core import di
from mugen.core.api import api
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.ipc import IIPCService, IPCCommandRequest
from mugen.core.plugin.wechat.api.decorator import (
    wechat_platform_required,
    wechat_provider_required,
    wechat_webhook_path_token_required,
)


def _config_provider():
    return di.container.config


def _ipc_provider():
    return di.container.ipc_service


def _logger_provider():
    return di.container.logging_gateway


def _coerce_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _required_query_arg(name: str) -> str:
    value = _coerce_text(request.args.get(name))
    if value == "":
        abort(400)
    return value


def _compute_signature(*, token: str, timestamp: str, nonce: str, encrypted: str | None) -> str:
    values = [token, timestamp, nonce]
    if isinstance(encrypted, str) and encrypted != "":
        values.append(encrypted)
    values.sort()
    joined = "".join(values)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def _verify_signature(
    *,
    token: str,
    timestamp: str,
    nonce: str,
    supplied_signature: str,
    encrypted: str | None = None,
) -> bool:
    expected = _compute_signature(
        token=token,
        timestamp=timestamp,
        nonce=nonce,
        encrypted=encrypted,
    )
    return hmac.compare_digest(expected, supplied_signature)


def _decode_aes_key(aes_key: str) -> bytes:
    padded = aes_key + ("=" * ((4 - (len(aes_key) % 4)) % 4))
    return base64.b64decode(padded)


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 32:
        raise ValueError("Invalid PKCS7 padding.")
    return data[:-pad_len]


def _decrypt_wechat_payload(*, encrypted: str, aes_key: str) -> str:
    aes_key_bytes = _decode_aes_key(aes_key)
    if len(aes_key_bytes) != 32:
        raise ValueError("Invalid WeChat AES key length.")

    cipher = Cipher(
        algorithms.AES(aes_key_bytes),
        modes.CBC(aes_key_bytes[:16]),
    )
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(base64.b64decode(encrypted)) + decryptor.finalize()
    decrypted = _pkcs7_unpad(decrypted)

    if len(decrypted) < 20:
        raise ValueError("WeChat payload too short.")

    xml_length = struct.unpack("!I", decrypted[16:20])[0]
    xml_bytes = decrypted[20 : 20 + xml_length]
    return xml_bytes.decode("utf-8")


def _parse_xml_payload(xml_text: str) -> dict:
    root = ElementTree.fromstring(xml_text)
    payload: dict[str, object] = {}
    for child in list(root):
        payload[child.tag] = child.text
    return payload


def _resolve_signature_token(config: SimpleNamespace) -> str:
    return str(config.wechat.webhook.signature_token)


def _resolve_aes_enabled(config: SimpleNamespace) -> bool:
    return bool(config.wechat.webhook.aes_enabled)


def _resolve_aes_key(config: SimpleNamespace) -> str:
    return str(config.wechat.webhook.aes_key)


def _verify_get_signature_or_abort(
    *,
    config: SimpleNamespace,
    logger: ILoggingGateway,
    timestamp: str,
    nonce: str,
    echostr: str,
) -> str:
    signature_token = _resolve_signature_token(config)
    aes_enabled = _resolve_aes_enabled(config)

    if aes_enabled is True:
        msg_signature = _coerce_text(request.args.get("msg_signature"))
        if msg_signature == "":
            logger.error("WeChat msg_signature not supplied.")
            abort(400)

        verified = _verify_signature(
            token=signature_token,
            timestamp=timestamp,
            nonce=nonce,
            supplied_signature=msg_signature,
            encrypted=echostr,
        )
        if verified is not True:
            logger.error("WeChat webhook signature verification failed.")
            abort(401)

        try:
            return _decrypt_wechat_payload(
                encrypted=echostr,
                aes_key=_resolve_aes_key(config),
            )
        except ValueError:
            logger.error("Unable to decrypt WeChat handshake payload.")
            abort(400)

    supplied_signature = _coerce_text(request.args.get("signature"))
    if supplied_signature == "":
        supplied_signature = _coerce_text(request.args.get("msg_signature"))
    if supplied_signature == "":
        logger.error("WeChat signature not supplied.")
        abort(400)

    verified = _verify_signature(
        token=signature_token,
        timestamp=timestamp,
        nonce=nonce,
        supplied_signature=supplied_signature,
    )
    if verified is not True:
        logger.error("WeChat webhook signature verification failed.")
        abort(401)

    return echostr


async def _resolve_inbound_payload_or_abort(
    *,
    config: SimpleNamespace,
    logger: ILoggingGateway,
) -> dict:
    timestamp = _required_query_arg("timestamp")
    nonce = _required_query_arg("nonce")

    body_bytes = await request.get_data()
    body_text = body_bytes.decode("utf-8", errors="ignore")

    try:
        outer_payload = _parse_xml_payload(body_text)
    except ElementTree.ParseError:
        logger.error("Malformed WeChat XML payload.")
        abort(400)

    signature_token = _resolve_signature_token(config)
    encrypted = _coerce_text(outer_payload.get("Encrypt"))
    aes_enabled = _resolve_aes_enabled(config)

    if encrypted != "":
        msg_signature = _coerce_text(request.args.get("msg_signature"))
        if msg_signature == "":
            logger.error("WeChat msg_signature not supplied for encrypted payload.")
            abort(400)

        verified = _verify_signature(
            token=signature_token,
            timestamp=timestamp,
            nonce=nonce,
            supplied_signature=msg_signature,
            encrypted=encrypted,
        )
        if verified is not True:
            logger.error("WeChat encrypted webhook signature verification failed.")
            abort(401)

        try:
            body_text = _decrypt_wechat_payload(
                encrypted=encrypted,
                aes_key=_resolve_aes_key(config),
            )
        except ValueError:
            logger.error("Unable to decrypt WeChat encrypted payload.")
            abort(400)
    elif aes_enabled is True:
        logger.error("Expected encrypted WeChat payload for AES-enabled webhook.")
        abort(400)
    else:
        supplied_signature = _coerce_text(request.args.get("signature"))
        if supplied_signature == "":
            supplied_signature = _coerce_text(request.args.get("msg_signature"))
        if supplied_signature == "":
            logger.error("WeChat signature not supplied for plaintext payload.")
            abort(400)

        verified = _verify_signature(
            token=signature_token,
            timestamp=timestamp,
            nonce=nonce,
            supplied_signature=supplied_signature,
        )
        if verified is not True:
            logger.error("WeChat plaintext webhook signature verification failed.")
            abort(401)

    try:
        payload = _parse_xml_payload(body_text)
    except ElementTree.ParseError:
        logger.error("Malformed WeChat XML payload.")
        abort(400)

    payload["_received_at"] = datetime.now(timezone.utc).isoformat()
    return payload


async def _handle_get_verification(
    *,
    config_provider,
    logger_provider,
) -> str:
    config: SimpleNamespace = config_provider()
    logger: ILoggingGateway = logger_provider()

    timestamp = _required_query_arg("timestamp")
    nonce = _required_query_arg("nonce")
    echostr = _required_query_arg("echostr")
    return _verify_get_signature_or_abort(
        config=config,
        logger=logger,
        timestamp=timestamp,
        nonce=nonce,
        echostr=echostr,
    )


async def _handle_post_event(
    *,
    path_token: str,
    provider: str,
    command: str,
    config_provider,
    ipc_provider,
    logger_provider,
) -> str:
    config: SimpleNamespace = config_provider()
    ipc_svc: IIPCService = ipc_provider()
    logger: ILoggingGateway = logger_provider()

    payload = await _resolve_inbound_payload_or_abort(
        config=config,
        logger=logger,
    )

    response = await ipc_svc.handle_ipc_request(
        IPCCommandRequest(
            platform="wechat",
            command=command,
            data={
                "path_token": path_token,
                "provider": provider,
                "payload": payload,
            },
        )
    )
    if response.errors:
        logger.warning(
            "WeChat webhook processed with IPC errors "
            f"command={command} error_count={len(response.errors)}"
        )
    return "success"


@api.get("/wechat/official_account/webhook/<path_token>")
@wechat_platform_required
@wechat_webhook_path_token_required
@wechat_provider_required("official_account")
async def wechat_official_account_subscription(
    path_token: str,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """Official Account URL verification endpoint."""
    _ = path_token
    return await _handle_get_verification(
        config_provider=config_provider,
        logger_provider=logger_provider,
    )


@api.post("/wechat/official_account/webhook/<path_token>")
@wechat_platform_required
@wechat_webhook_path_token_required
@wechat_provider_required("official_account")
async def wechat_official_account_event(
    path_token: str,
    config_provider=_config_provider,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
):
    """Official Account webhook event endpoint."""
    _ = path_token
    return await _handle_post_event(
        path_token=path_token,
        provider="official_account",
        command="wechat_official_account_event",
        config_provider=config_provider,
        ipc_provider=ipc_provider,
        logger_provider=logger_provider,
    )


@api.get("/wechat/wecom/callback/<path_token>")
@wechat_platform_required
@wechat_webhook_path_token_required
@wechat_provider_required("wecom")
async def wechat_wecom_subscription(
    path_token: str,
    config_provider=_config_provider,
    logger_provider=_logger_provider,
):
    """WeCom callback URL verification endpoint."""
    _ = path_token
    return await _handle_get_verification(
        config_provider=config_provider,
        logger_provider=logger_provider,
    )


@api.post("/wechat/wecom/callback/<path_token>")
@wechat_platform_required
@wechat_webhook_path_token_required
@wechat_provider_required("wecom")
async def wechat_wecom_event(
    path_token: str,
    config_provider=_config_provider,
    ipc_provider=_ipc_provider,
    logger_provider=_logger_provider,
):
    """WeCom callback event endpoint."""
    _ = path_token
    return await _handle_post_event(
        path_token=path_token,
        provider="wecom",
        command="wechat_wecom_event",
        config_provider=config_provider,
        ipc_provider=ipc_provider,
        logger_provider=logger_provider,
    )
