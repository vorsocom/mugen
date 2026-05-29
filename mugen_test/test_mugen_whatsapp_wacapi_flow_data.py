"""Unit tests for WhatsApp Flow Data endpoint support."""

from __future__ import annotations

import base64
import hashlib
import hmac
from inspect import unwrap
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from mugen.core.plugin.whatsapp.wacapi import flow_data as flow_data_contracts
from mugen.core.plugin.whatsapp.wacapi.api import flow_data as flow_data_api


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _private_key_pem(private_key, *, passphrase: str | None = None) -> str:
    if passphrase:
        encryption_algorithm = serialization.BestAvailableEncryption(
            passphrase.encode("utf-8")
        )
    else:
        encryption_algorithm = serialization.NoEncryption()
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption_algorithm,
    ).decode("ascii")


def _encrypt_flow_request(
    *,
    private_key,
    payload: object,
    aes_key: bytes = bytes(range(32)),
    initial_vector: bytes = bytes(range(16)),
) -> tuple[dict, bytes, bytes, bytes]:
    encrypted_flow_data = AESGCM(aes_key).encrypt(
        initial_vector,
        json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        None,
    )
    encrypted_aes_key = private_key.public_key().encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    envelope = {
        "encrypted_flow_data": base64.b64encode(encrypted_flow_data).decode(
            "ascii"
        ),
        "encrypted_aes_key": base64.b64encode(encrypted_aes_key).decode(
            "ascii"
        ),
        "initial_vector": base64.b64encode(initial_vector).decode("ascii"),
    }
    raw_body = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    return envelope, raw_body, aes_key, initial_vector


def _signature(raw_body: bytes, *, app_secret: str = "app-secret") -> str:
    digest = hmac.new(
        app_secret.encode("utf8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _flip_initial_vector(initial_vector: bytes) -> bytes:
    return bytes(byte ^ 0xFF for byte in initial_vector)


def _decrypt_flow_response(
    encrypted_response: str,
    *,
    aes_key: bytes,
    initial_vector: bytes,
) -> dict:
    decrypted = AESGCM(aes_key).decrypt(
        _flip_initial_vector(initial_vector),
        base64.b64decode(encrypted_response),
        None,
    )
    return json.loads(decrypted.decode("utf-8"))


def _runtime_config(private_key_pem: str, *, app_secret: str = "app-secret"):
    return SimpleNamespace(
        whatsapp=SimpleNamespace(
            app=SimpleNamespace(secret=app_secret),
            flows=SimpleNamespace(
                private_key=private_key_pem,
                private_key_passphrase=None,
            ),
        )
    )


def _client_profile() -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000208",
        tenant_id="11111111-1111-1111-1111-111111111111",
        platform_key="whatsapp",
        profile_key="whatsapp-a",
        path_token="path-token",
        phone_number_id="15550000001",
    )


class TestWhatsAppFlowDataCrypto(unittest.TestCase):
    """Covers WhatsApp Flow Data cryptographic envelope handling."""

    def test_crypto_round_trip_with_generated_material(self) -> None:
        private_key = _private_key()
        plaintext_request = {
            "version": "3.0",
            "flow_token": "flow-token",
            "action": "data_exchange",
            "screen": "DETAILS",
            "data": {"flow_name": "booking"},
        }
        envelope, _raw_body, aes_key, initial_vector = _encrypt_flow_request(
            private_key=private_key,
            payload=plaintext_request,
        )

        decrypted_request, crypto_material = (
            flow_data_contracts.decrypt_flow_data_request(
                envelope,
                private_key_pem=_private_key_pem(private_key),
            )
        )
        self.assertEqual(decrypted_request, plaintext_request)
        self.assertEqual(crypto_material.aes_key, aes_key)
        self.assertEqual(crypto_material.initial_vector, initial_vector)

        encrypted_response = flow_data_contracts.encrypt_flow_data_response(
            {"data": {"ok": True}},
            crypto_material=crypto_material,
        )
        self.assertEqual(
            _decrypt_flow_response(
                encrypted_response,
                aes_key=aes_key,
                initial_vector=initial_vector,
            ),
            {"data": {"ok": True}},
        )

    def test_encrypted_private_key_passphrase_is_supported(self) -> None:
        private_key = _private_key()
        envelope, _raw_body, _aes_key, _initial_vector = _encrypt_flow_request(
            private_key=private_key,
            payload={"action": "ping", "data": {}},
        )

        decrypted_request, _crypto_material = (
            flow_data_contracts.decrypt_flow_data_request(
                envelope,
                private_key_pem=_private_key_pem(
                    private_key,
                    passphrase="flow-passphrase",
                ),
                private_key_passphrase="flow-passphrase",
            )
        )

        self.assertEqual(decrypted_request, {"action": "ping", "data": {}})

    def test_crypto_error_paths(self) -> None:
        private_key = _private_key()
        envelope, _raw_body, _aes_key, _initial_vector = _encrypt_flow_request(
            private_key=private_key,
            payload={"action": "ping", "data": {}},
        )

        error_cases = [
            (
                lambda: flow_data_contracts.decrypt_flow_data_request(
                    [],
                    private_key_pem=_private_key_pem(private_key),
                ),
                "Flow Data request must be a JSON object",
            ),
            (
                lambda: flow_data_contracts.decrypt_flow_data_request(
                    {},
                    private_key_pem=_private_key_pem(private_key),
                ),
                "encrypted_aes_key must be non-empty",
            ),
            (
                lambda: flow_data_contracts.decrypt_flow_data_request(
                    {"encrypted_aes_key": "***"},
                    private_key_pem=_private_key_pem(private_key),
                ),
                "encrypted_aes_key must be valid base64",
            ),
            (
                lambda: flow_data_contracts.decrypt_flow_data_request(
                    envelope,
                    private_key_pem=" ",
                ),
                "Flow private key must be non-empty",
            ),
            (
                lambda: flow_data_contracts.decrypt_flow_data_request(
                    envelope,
                    private_key_pem="not-a-private-key",
                ),
                "Flow private key could not be loaded",
            ),
            (
                lambda: flow_data_contracts.decrypt_flow_data_request(
                    envelope,
                    private_key_pem=_private_key_pem(_private_key()),
                ),
                "Flow Data request could not be decrypted",
            ),
            (
                lambda: flow_data_contracts.encrypt_flow_data_response(
                    [],
                    crypto_material=flow_data_contracts.WhatsAppFlowDataCryptoMaterial(
                        aes_key=bytes(range(32)),
                        initial_vector=bytes(range(16)),
                    ),
                ),
                "Flow Data response must be a JSON object",
            ),
            (
                lambda: flow_data_contracts.encrypt_flow_data_response(
                    {"data": {}},
                    crypto_material=flow_data_contracts.WhatsAppFlowDataCryptoMaterial(
                        aes_key=b"short",
                        initial_vector=bytes(range(16)),
                    ),
                ),
                "Flow Data response could not be encrypted",
            ),
        ]
        for fn, message in error_cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(
                    flow_data_contracts.WhatsAppFlowDataCryptoError,
                    message,
                ):
                    fn()

    def test_crypto_rejects_decrypted_non_object_payload(self) -> None:
        private_key = _private_key()
        envelope, _raw_body, _aes_key, _initial_vector = _encrypt_flow_request(
            private_key=private_key,
            payload=[],
        )

        with self.assertRaisesRegex(
            flow_data_contracts.WhatsAppFlowDataCryptoError,
            "Decrypted Flow Data payload is invalid",
        ):
            flow_data_contracts.decrypt_flow_data_request(
                envelope,
                private_key_pem=_private_key_pem(private_key),
            )


class TestWhatsAppFlowDataRegistry(unittest.IsolatedAsyncioTestCase):
    """Covers built-in and registered Flow Data handler dispatch."""

    def _request(
        self,
        *,
        action: str = "data_exchange",
        screen: str = "DETAILS",
        flow_name: str | None = "booking",
        data: dict | None = None,
    ) -> flow_data_contracts.WhatsAppFlowDataRequest:
        return flow_data_contracts.WhatsAppFlowDataRequest(
            tenant_id="tenant-1",
            client_profile_id="profile-1",
            client_profile_key="whatsapp-a",
            phone_number_id="15550000001",
            path_token="path-token",
            runtime_config=SimpleNamespace(),
            flow_token="flow-token",
            flow_name=flow_name,
            action=action,
            screen=screen,
            data=dict(data or {}),
            raw_payload={},
        )

    async def test_builtin_ping_and_error_ack_do_not_need_handlers(self) -> None:
        registry = flow_data_contracts.WhatsAppFlowDataRegistry()

        self.assertEqual(
            await registry.handle_flow_data(self._request(action="ping")),
            {"data": {"status": "active"}},
        )
        self.assertEqual(
            await registry.handle_flow_data(
                self._request(data={"error": "client validation failed"})
            ),
            {"data": {"acknowledged": True}},
        )

    async def test_specific_handler_wins_and_no_handler_raises(self) -> None:
        registry = flow_data_contracts.WhatsAppFlowDataRegistry()
        registry.register_handler(
            lambda _request: {"data": {"generic": True}},
        )
        registry.register_handler(
            lambda _request: {"data": {"specific": True}},
            flow_name="booking",
            action="data_exchange",
            screen="DETAILS",
        )

        self.assertEqual(
            await registry.handle_flow_data(self._request()),
            {"data": {"specific": True}},
        )

        empty_registry = flow_data_contracts.WhatsAppFlowDataRegistry()
        with self.assertRaises(flow_data_contracts.WhatsAppFlowDataNoHandlerError):
            await empty_registry.handle_flow_data(self._request())

    async def test_registry_rejects_bad_handler_and_result_shapes(self) -> None:
        registry = flow_data_contracts.WhatsAppFlowDataRegistry()
        with self.assertRaisesRegex(TypeError, "handler must be callable"):
            registry.register_handler(None)

        registry.register_handler(lambda _request: "bad-result")
        with self.assertRaisesRegex(RuntimeError, "unsupported result"):
            await registry.handle_flow_data(self._request())

    async def test_registry_skips_none_results_and_non_matching_handlers(self) -> None:
        registry = flow_data_contracts.WhatsAppFlowDataRegistry()
        registry.register_handler(
            lambda _request: None,
            flow_name="booking",
        )
        registry.register_handler(
            lambda _request: {"data": {"fallback": True}},
        )
        self.assertEqual(
            await registry.handle_flow_data(self._request()),
            {"data": {"fallback": True}},
        )

        non_matching_registry = flow_data_contracts.WhatsAppFlowDataRegistry()
        non_matching_registry.register_handler(
            lambda _request: {"data": {"wrong_flow": True}},
            flow_name="other-flow",
        )
        non_matching_registry.register_handler(
            lambda _request: {"data": {"wrong_action": True}},
            action="other-action",
        )
        non_matching_registry.register_handler(
            lambda _request: {"data": {"wrong_screen": True}},
            screen="OTHER_SCREEN",
        )
        with self.assertRaises(flow_data_contracts.WhatsAppFlowDataNoHandlerError):
            await non_matching_registry.handle_flow_data(self._request())


class TestWhatsAppFlowDataEndpoint(unittest.IsolatedAsyncioTestCase):
    """Covers Flow Data endpoint guard, dispatch, and error contracts."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
            get_ext_service=lambda _name, _default=None: "registry",
        )
        with patch.object(flow_data_api.di, "container", new=container):
            self.assertEqual(flow_data_api._config_provider(), "cfg")
            self.assertEqual(flow_data_api._logger_provider(), "logger")
            self.assertEqual(flow_data_api._flow_data_registry_provider(), "registry")
            self.assertIsNone(flow_data_api._client_profile_service())

        with patch.object(
            flow_data_api,
            "MessagingClientProfileService",
            return_value="service",
        ) as service_cls:
            container = SimpleNamespace(relational_storage_gateway="rsg")
            with patch.object(flow_data_api.di, "container", new=container):
                self.assertEqual(flow_data_api._client_profile_service(), "service")
        service_cls.assert_called_once_with(
            table="admin_messaging_client_profile",
            rsg="rsg",
        )

    async def test_signature_helper_rejects_missing_header(self) -> None:
        logger = Mock()
        with patch.object(
            flow_data_api,
            "request",
            new=SimpleNamespace(headers={}),
        ):
            self.assertFalse(
                flow_data_api._verify_request_signature(
                    app_secret="app-secret",
                    raw_body=b"{}",
                    logger=logger,
                )
            )

        logger.error.assert_called_once_with(
            "Could not get WhatsApp Flow Data request hash."
        )

    async def _call_endpoint(
        self,
        *,
        plaintext_request: dict,
        registry: flow_data_contracts.WhatsAppFlowDataRegistry,
        signature: str | None = None,
        headers_override: dict | None = None,
        raw_body_override: bytes | None = None,
        private_key=None,
        runtime_config_override=None,
        logger=None,
    ):
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        private_key = private_key or _private_key()
        private_key_text = _private_key_pem(private_key)
        runtime_config = runtime_config_override or _runtime_config(private_key_text)
        client_profile = _client_profile()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=client_profile),
            build_runtime_config=AsyncMock(return_value=runtime_config),
        )

        _envelope, raw_body, aes_key, initial_vector = _encrypt_flow_request(
            private_key=private_key,
            payload=plaintext_request,
        )
        raw_body = raw_body_override or raw_body
        headers = headers_override
        if headers is None:
            headers = {
                "X-Hub-Signature-256": signature
                if signature is not None
                else _signature(raw_body)
            }

        with patch.object(
            flow_data_api,
            "request",
            new=SimpleNamespace(
                headers=headers,
                get_data=AsyncMock(return_value=raw_body),
            ),
        ):
            response = await endpoint(
                path_token="path-token",
                config_provider=lambda: SimpleNamespace(),
                logger_provider=lambda: logger or Mock(),
                client_profile_service_provider=lambda: service,
                flow_data_registry_provider=lambda: registry,
            )

        return (
            response,
            service,
            client_profile,
            runtime_config,
            aes_key,
            initial_vector,
        )

    async def test_ping_returns_encrypted_active_status(self) -> None:
        response, *_rest, aes_key, initial_vector = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
        )

        self.assertEqual(
            _decrypt_flow_response(
                response,
                aes_key=aes_key,
                initial_vector=initial_vector,
            ),
            {"data": {"status": "active"}},
        )

    async def test_non_dict_data_is_normalized_before_dispatch(self) -> None:
        response, *_rest, aes_key, initial_vector = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": []},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
        )

        self.assertEqual(
            _decrypt_flow_response(
                response,
                aes_key=aes_key,
                initial_vector=initial_vector,
            ),
            {"data": {"status": "active"}},
        )

    async def test_successful_handler_dispatch_includes_resolved_context(self) -> None:
        registry = flow_data_contracts.WhatsAppFlowDataRegistry()
        captured_requests: list[flow_data_contracts.WhatsAppFlowDataRequest] = []

        async def _handler(request):
            captured_requests.append(request)
            return {
                "screen": "CONFIRM",
                "data": {"phone_number_id": request.phone_number_id},
            }

        registry.register_handler(
            _handler,
            flow_name="booking",
            action="data_exchange",
            screen="DETAILS",
        )

        response, service, _profile, runtime_config, aes_key, initial_vector = (
            await self._call_endpoint(
                plaintext_request={
                    "version": "3.0",
                    "flow_token": "flow-token",
                    "action": "data_exchange",
                    "screen": "DETAILS",
                    "data": {"flow_name": "booking", "pickup": "GEO"},
                },
                registry=registry,
            )
        )

        self.assertEqual(
            _decrypt_flow_response(
                response,
                aes_key=aes_key,
                initial_vector=initial_vector,
            ),
            {
                "screen": "CONFIRM",
                "data": {"phone_number_id": "15550000001"},
            },
        )
        service.resolve_active_by_identifier.assert_awaited_once_with(
            platform_key="whatsapp",
            identifier_type="path_token",
            identifier_value="path-token",
        )
        service.build_runtime_config.assert_awaited_once()
        request_context = captured_requests[0]
        self.assertEqual(
            request_context.tenant_id,
            "11111111-1111-1111-1111-111111111111",
        )
        self.assertEqual(
            request_context.client_profile_id,
            "00000000-0000-0000-0000-000000000208",
        )
        self.assertEqual(request_context.client_profile_key, "whatsapp-a")
        self.assertEqual(request_context.phone_number_id, "15550000001")
        self.assertEqual(request_context.path_token, "path-token")
        self.assertIs(request_context.runtime_config, runtime_config)
        self.assertEqual(request_context.flow_token, "flow-token")
        self.assertEqual(request_context.flow_name, "booking")
        self.assertEqual(request_context.action, "data_exchange")
        self.assertEqual(request_context.screen, "DETAILS")
        self.assertEqual(request_context.data["pickup"], "GEO")

    async def test_bad_signature_returns_432(self) -> None:
        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
            signature="sha256=bad-signature",
        )

        self.assertEqual(response, ("", 432))

    async def test_missing_signature_returns_432(self) -> None:
        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
            headers_override={},
        )

        self.assertEqual(response, ("", 432))

    async def test_malformed_json_returns_421(self) -> None:
        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
            raw_body_override=b"{",
        )

        self.assertEqual(response, ("", 421))

    async def test_non_object_payload_returns_421(self) -> None:
        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
            raw_body_override=b"[]",
        )

        self.assertEqual(response, ("", 421))

    async def test_bad_encryption_returns_421(self) -> None:
        raw_body = json.dumps(
            {
                "encrypted_flow_data": "bad",
                "encrypted_aes_key": "bad",
                "initial_vector": "bad",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
            raw_body_override=raw_body,
        )

        self.assertEqual(response, ("", 421))

    async def test_missing_private_key_returns_421(self) -> None:
        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "ping", "data": {}},
            registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
            runtime_config_override=SimpleNamespace(
                whatsapp=SimpleNamespace(
                    app=SimpleNamespace(secret="app-secret"),
                    flows=SimpleNamespace(),
                )
            ),
        )

        self.assertEqual(response, ("", 421))

    async def test_invalid_flow_token_returns_427(self) -> None:
        registry = flow_data_contracts.WhatsAppFlowDataRegistry()

        async def _handler(_request):
            raise flow_data_contracts.WhatsAppFlowDataInvalidTokenError(
                "Flow token expired."
            )

        registry.register_handler(_handler, action="data_exchange")

        response, *_rest = await self._call_endpoint(
            plaintext_request={"action": "data_exchange", "data": {}},
            registry=registry,
        )

        self.assertEqual(response, ({"error_msg": "Flow token expired."}, 427))

    async def test_no_handler_aborts_500(self) -> None:
        with patch.object(flow_data_api, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call_endpoint(
                    plaintext_request={"action": "data_exchange", "data": {}},
                    registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_missing_client_profile_service_aborts_500(self) -> None:
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        with (
            patch.object(flow_data_api, "abort", side_effect=_abort_raiser),
            patch.object(flow_data_api, "_client_profile_service", return_value=None),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: Mock(),
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_non_callable_client_profile_provider_aborts_500(self) -> None:
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        with patch.object(flow_data_api, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: Mock(),
                    client_profile_service_provider=object(),
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_empty_path_token_aborts_400(self) -> None:
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(),
            build_runtime_config=AsyncMock(),
        )
        with patch.object(flow_data_api, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token=" ",
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: Mock(),
                    client_profile_service_provider=lambda: service,
                )

        self.assertEqual(ex.exception.code, 400)

    async def test_profile_resolution_exception_aborts_500(self) -> None:
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                side_effect=RuntimeError("storage unavailable")
            ),
            build_runtime_config=AsyncMock(),
        )
        with patch.object(flow_data_api, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: Mock(),
                    client_profile_service_provider=lambda: service,
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_missing_app_secret_aborts_500(self) -> None:
        with patch.object(flow_data_api, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call_endpoint(
                    plaintext_request={"action": "ping", "data": {}},
                    registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
                    runtime_config_override=SimpleNamespace(
                        whatsapp=SimpleNamespace(
                            app=SimpleNamespace(),
                            flows=SimpleNamespace(private_key="unused"),
                        )
                    ),
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_missing_flow_data_registry_aborts_500(self) -> None:
        with patch.object(flow_data_api, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call_endpoint(
                    plaintext_request={"action": "ping", "data": {}},
                    registry=None,
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_non_callable_flow_data_registry_provider_aborts_500(self) -> None:
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        private_key = _private_key()
        private_key_text = _private_key_pem(private_key)
        runtime_config = _runtime_config(private_key_text)
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=_client_profile()),
            build_runtime_config=AsyncMock(return_value=runtime_config),
        )
        _envelope, raw_body, _aes_key, _initial_vector = _encrypt_flow_request(
            private_key=private_key,
            payload={"action": "ping", "data": {}},
        )

        with (
            patch.object(flow_data_api, "abort", side_effect=_abort_raiser),
            patch.object(
                flow_data_api,
                "request",
                new=SimpleNamespace(
                    headers={"X-Hub-Signature-256": _signature(raw_body)},
                    get_data=AsyncMock(return_value=raw_body),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="path-token",
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: Mock(),
                    client_profile_service_provider=lambda: service,
                    flow_data_registry_provider=object(),
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_response_encryption_failure_aborts_500(self) -> None:
        with (
            patch.object(flow_data_api, "abort", side_effect=_abort_raiser),
            patch.object(
                flow_data_api,
                "encrypt_flow_data_response",
                side_effect=flow_data_contracts.WhatsAppFlowDataCryptoError(
                    "encrypt failed"
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await self._call_endpoint(
                    plaintext_request={"action": "ping", "data": {}},
                    registry=flow_data_contracts.WhatsAppFlowDataRegistry(),
                )

        self.assertEqual(ex.exception.code, 500)

    async def test_path_token_resolution_failure_aborts_401(self) -> None:
        endpoint = unwrap(flow_data_api.whatsapp_wacapi_flow_data)
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=None),
            build_runtime_config=AsyncMock(),
        )
        with (
            patch.object(flow_data_api, "abort", side_effect=_abort_raiser),
            patch.object(
                flow_data_api,
                "request",
                new=SimpleNamespace(headers={}, get_data=AsyncMock(return_value=b"{}")),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await endpoint(
                    path_token="missing-path-token",
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: Mock(),
                    client_profile_service_provider=lambda: service,
                    flow_data_registry_provider=lambda: (
                        flow_data_contracts.WhatsAppFlowDataRegistry()
                    ),
                )

        self.assertEqual(ex.exception.code, 401)
        service.resolve_active_by_identifier.assert_awaited_once_with(
            platform_key="whatsapp",
            identifier_type="path_token",
            identifier_value="missing-path-token",
        )


if __name__ == "__main__":
    unittest.main()
