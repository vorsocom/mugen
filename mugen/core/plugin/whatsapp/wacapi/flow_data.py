"""WhatsApp Flow Data endpoint contracts and crypto helpers."""

from __future__ import annotations

__all__ = [
    "WhatsAppFlowDataCryptoMaterial",
    "WhatsAppFlowDataCryptoError",
    "WhatsAppFlowDataHandlerError",
    "WhatsAppFlowDataInvalidTokenError",
    "WhatsAppFlowDataNoHandlerError",
    "WhatsAppFlowDataRegistry",
    "WhatsAppFlowDataRequest",
    "decrypt_flow_data_request",
    "encrypt_flow_data_response",
]

import base64
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


WhatsAppFlowDataHandler = Callable[
    ["WhatsAppFlowDataRequest"],
    dict[str, Any] | Awaitable[dict[str, Any] | None] | None,
]


class WhatsAppFlowDataCryptoError(RuntimeError):
    """Raised when encrypted Flow Data request handling fails."""


class WhatsAppFlowDataHandlerError(RuntimeError):
    """Base class for handler-level Flow Data errors."""


class WhatsAppFlowDataNoHandlerError(WhatsAppFlowDataHandlerError):
    """Raised when no handler is registered for a Flow Data request."""


class WhatsAppFlowDataInvalidTokenError(WhatsAppFlowDataHandlerError):
    """Raised when a Flow token is no longer usable."""

    def __init__(self, error_msg: str = "The Flow token is no longer valid.") -> None:
        super().__init__(error_msg)
        self.error_msg = error_msg


@dataclass(frozen=True, slots=True)
class WhatsAppFlowDataCryptoMaterial:
    """Decrypted symmetric material for one Flow Data exchange."""

    aes_key: bytes
    initial_vector: bytes


@dataclass(frozen=True, slots=True)
class WhatsAppFlowDataRequest:
    """Normalized request passed to downstream Flow Data handlers."""

    tenant_id: uuid.UUID | str | None
    client_profile_id: uuid.UUID | str | None
    client_profile_key: str | None
    phone_number_id: str | None
    path_token: str
    runtime_config: SimpleNamespace
    flow_token: str | None
    flow_name: str | None
    action: str | None
    screen: str | None
    data: dict[str, Any]
    raw_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _HandlerBinding:
    handler: WhatsAppFlowDataHandler
    flow_name: str | None
    action: str | None
    screen: str | None
    index: int

    @property
    def specificity(self) -> int:
        return sum(
            item is not None
            for item in (
                self.flow_name,
                self.action,
                self.screen,
            )
        )


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _decode_base64_field(value: object, *, field_name: str) -> bytes:
    if not isinstance(value, str) or value.strip() == "":
        raise WhatsAppFlowDataCryptoError(f"{field_name} must be non-empty.")
    try:
        return base64.b64decode(value, validate=True)
    except (TypeError, ValueError) as exc:
        raise WhatsAppFlowDataCryptoError(
            f"{field_name} must be valid base64."
        ) from exc


def _load_private_key(private_key_pem: str, passphrase: str | None):
    if not isinstance(private_key_pem, str) or private_key_pem.strip() == "":
        raise WhatsAppFlowDataCryptoError("Flow private key must be non-empty.")

    password = passphrase.encode("utf-8") if passphrase not in [None, ""] else None
    try:
        return serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=password,
        )
    except (TypeError, ValueError) as exc:
        raise WhatsAppFlowDataCryptoError(
            "Flow private key could not be loaded."
        ) from exc


def _flip_initial_vector(initial_vector: bytes) -> bytes:
    return bytes(byte ^ 0xFF for byte in initial_vector)


def decrypt_flow_data_request(
    payload: dict[str, Any],
    *,
    private_key_pem: str,
    private_key_passphrase: str | None = None,
) -> tuple[dict[str, Any], WhatsAppFlowDataCryptoMaterial]:
    """Decrypt a WhatsApp Flow Data request envelope."""
    if not isinstance(payload, dict):
        raise WhatsAppFlowDataCryptoError("Flow Data request must be a JSON object.")

    encrypted_aes_key = _decode_base64_field(
        payload.get("encrypted_aes_key"),
        field_name="encrypted_aes_key",
    )
    encrypted_flow_data = _decode_base64_field(
        payload.get("encrypted_flow_data"),
        field_name="encrypted_flow_data",
    )
    initial_vector = _decode_base64_field(
        payload.get("initial_vector"),
        field_name="initial_vector",
    )

    private_key = _load_private_key(private_key_pem, private_key_passphrase)
    try:
        aes_key = private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        decrypted_data = AESGCM(aes_key).decrypt(
            initial_vector,
            encrypted_flow_data,
            None,
        )
        decoded_payload = json.loads(decrypted_data.decode("utf-8"))
    except (
        InvalidTag,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise WhatsAppFlowDataCryptoError(
            "Flow Data request could not be decrypted."
        ) from exc

    if not isinstance(decoded_payload, dict):
        raise WhatsAppFlowDataCryptoError("Decrypted Flow Data payload is invalid.")

    return (
        decoded_payload,
        WhatsAppFlowDataCryptoMaterial(
            aes_key=aes_key,
            initial_vector=initial_vector,
        ),
    )


def encrypt_flow_data_response(
    payload: dict[str, Any],
    *,
    crypto_material: WhatsAppFlowDataCryptoMaterial,
) -> str:
    """Encrypt a Flow Data response payload for WhatsApp."""
    if not isinstance(payload, dict):
        raise WhatsAppFlowDataCryptoError("Flow Data response must be a JSON object.")

    try:
        response_body = json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted_response = AESGCM(crypto_material.aes_key).encrypt(
            _flip_initial_vector(crypto_material.initial_vector),
            response_body,
            None,
        )
    except (TypeError, ValueError) as exc:
        raise WhatsAppFlowDataCryptoError(
            "Flow Data response could not be encrypted."
        ) from exc

    return base64.b64encode(encrypted_response).decode("ascii")


class WhatsAppFlowDataRegistry:
    """Dispatches decrypted Flow Data requests to downstream handlers."""

    def __init__(self) -> None:
        self._bindings: list[_HandlerBinding] = []

    def register_handler(
        self,
        handler: WhatsAppFlowDataHandler,
        *,
        flow_name: str | None = None,
        action: str | None = None,
        screen: str | None = None,
    ) -> None:
        """Register a downstream handler for matching Flow Data requests."""
        if not callable(handler):
            raise TypeError("handler must be callable.")

        self._bindings.append(
            _HandlerBinding(
                handler=handler,
                flow_name=_normalize_optional_text(flow_name),
                action=_normalize_optional_text(action),
                screen=_normalize_optional_text(screen),
                index=len(self._bindings),
            )
        )

    @staticmethod
    def _matches(binding: _HandlerBinding, request: WhatsAppFlowDataRequest) -> bool:
        if binding.flow_name is not None and binding.flow_name != request.flow_name:
            return False
        if binding.action is not None and binding.action != request.action:
            return False
        if binding.screen is not None and binding.screen != request.screen:
            return False
        return True

    async def handle_flow_data(
        self,
        request: WhatsAppFlowDataRequest,
    ) -> dict[str, Any]:
        """Return response data for a decrypted Flow Data request."""
        if request.action == "ping":
            return {"data": {"status": "active"}}

        if "error" in request.data:
            return {"data": {"acknowledged": True}}

        candidates = sorted(
            (
                binding
                for binding in self._bindings
                if self._matches(binding, request)
            ),
            key=lambda item: (-item.specificity, item.index),
        )
        for binding in candidates:
            result = binding.handler(request)
            if inspect.isawaitable(result):
                result = await result
            if result is None:
                continue
            if not isinstance(result, dict):
                raise RuntimeError("Flow Data handler returned unsupported result.")
            return result

        raise WhatsAppFlowDataNoHandlerError("No Flow Data handler matched request.")
