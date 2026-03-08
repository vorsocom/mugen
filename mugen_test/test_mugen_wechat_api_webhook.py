"""Unit tests for mugen.core.plugin.wechat.api.webhook."""

from inspect import unwrap
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.service.ipc import IPCAggregateError, IPCAggregateResult
from mugen.core.plugin.wechat.api import webhook
from mugen.core.utility.platform_runtime_profile import build_config_namespace


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(*, aes_enabled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        wechat=SimpleNamespace(
            webhook=SimpleNamespace(
                signature_token="signature-token-1",
                aes_enabled=aes_enabled,
                aes_key="0123456789abcdef0123456789abcdef0123456789A",
            )
        )
    )


def _make_multi_profile_config(*, aes_enabled: bool = False) -> SimpleNamespace:
    return build_config_namespace(
        {
            "wechat": {
                "profiles": [
                    {
                        "key": "default",
                        "provider": "official_account",
                        "webhook": {
                            "path_token": "path-token-1",
                            "signature_token": "signature-token-1",
                            "aes_enabled": aes_enabled,
                            "aes_key": "0123456789abcdef0123456789abcdef0123456789A",
                        },
                    }
                ]
            }
        }
    )


class TestMugenWeChatWebhook(unittest.IsolatedAsyncioTestCase):
    """Covers webhook helper, verification, and endpoint dispatch branches."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            ingress_service="ingress",
            ipc_service="ipc",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
        )
        with patch.object(webhook.di, "container", new=container):
            self.assertEqual(webhook._config_provider(), "cfg")
            self.assertEqual(webhook._ingress_provider(), "ingress")
            self.assertEqual(webhook._ipc_provider(), "ipc")
            self.assertEqual(webhook._logger_provider(), "logger")
            self.assertEqual(webhook._relational_storage_gateway_provider(), "rsg")

    async def test_signature_and_xml_helpers(self) -> None:
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token="t",
            timestamp="2",
            nonce="1",
            encrypted=None,
        )
        self.assertTrue(
            webhook._verify_signature(  # pylint: disable=protected-access
                token="t",
                timestamp="2",
                nonce="1",
                supplied_signature=signature,
                encrypted=None,
            )
        )

        xml_payload = webhook._parse_xml_payload("<xml><MsgType>text</MsgType></xml>")  # pylint: disable=protected-access
        self.assertEqual(xml_payload["MsgType"], "text")
        self.assertEqual(webhook._coerce_text(None), "")  # pylint: disable=protected-access

    async def test_wechat_profile_config_supports_legacy_fallback_and_error_paths(
        self,
    ) -> None:
        legacy_config = _make_config(aes_enabled=False)
        profile = webhook._wechat_profile_config(  # pylint: disable=protected-access
            legacy_config,
            path_token=None,
        )
        self.assertIs(profile, legacy_config.wechat)

        with self.assertRaises(RuntimeError):
            webhook._wechat_profile_config(  # pylint: disable=protected-access
                SimpleNamespace(),
                path_token=None,
            )

        with patch.object(
            webhook,
            "identifier_configured_for_platform",
            side_effect=RuntimeError("bad config"),
        ):
            with self.assertRaises(RuntimeError):
                webhook._wechat_profile_config(  # pylint: disable=protected-access
                    _make_multi_profile_config(),
                    path_token="path-token-1",
                )

        with self.assertRaises(RuntimeError):
            webhook._wechat_profile_config(  # pylint: disable=protected-access
                _make_multi_profile_config(),
                path_token="missing-token",
            )

    async def test_required_query_arg_missing_aborts(self) -> None:
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(webhook, "request", new=SimpleNamespace(args={})),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                webhook._required_query_arg("timestamp")  # pylint: disable=protected-access
            self.assertEqual(ex.exception.code, 400)

    async def test_pkcs7_unpad_and_decrypt_error_branches(self) -> None:
        self.assertEqual(webhook._pkcs7_unpad(b""), b"")  # pylint: disable=protected-access
        self.assertEqual(webhook._pkcs7_unpad(b"abc\x01"), b"abc")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            webhook._pkcs7_unpad(b"abc\x00")  # pylint: disable=protected-access

        with (
            patch.object(webhook, "_decode_aes_key", return_value=b"x" * 16),
            self.assertRaises(ValueError),
        ):
            webhook._decrypt_wechat_payload(  # pylint: disable=protected-access
                encrypted="AA==",
                aes_key="bad-length",
            )

        class _ShortDecryptor:
            def update(self, _ciphertext: bytes) -> bytes:
                # 17 bytes total -> unpadded payload shorter than required 20 bytes.
                return b"A" * 16 + b"\x01"

            def finalize(self) -> bytes:
                return b""

        class _ShortCipher:
            def decryptor(self):
                return _ShortDecryptor()

        with (
            patch.object(webhook, "_decode_aes_key", return_value=b"x" * 32),
            patch.object(webhook, "Cipher", return_value=_ShortCipher()),
            self.assertRaises(ValueError),
        ):
            webhook._decrypt_wechat_payload(  # pylint: disable=protected-access
                encrypted="AA==",
                aes_key="short-payload",
            )

        with self.assertRaises(ValueError):
            webhook._decrypt_wechat_payload(  # pylint: disable=protected-access
                encrypted="bad-base64",
                aes_key="bad-key",
            )

    async def test_decrypt_wechat_payload_success_path(self) -> None:
        xml_text = "<xml><MsgType>text</MsgType></xml>"
        xml_bytes = xml_text.encode("utf-8")
        decrypted_payload = (
            b"0123456789ABCDEF"
            + struct.pack("!I", len(xml_bytes))
            + xml_bytes
            + b"\x01"
        )

        class _FakeDecryptor:
            def update(self, _ciphertext: bytes) -> bytes:
                return decrypted_payload

            def finalize(self) -> bytes:
                return b""

        class _FakeCipher:
            def decryptor(self):
                return _FakeDecryptor()

        with (
            patch.object(webhook, "_decode_aes_key", return_value=b"x" * 32),
            patch.object(webhook, "Cipher", return_value=_FakeCipher()),
        ):
            decrypted = webhook._decrypt_wechat_payload(  # pylint: disable=protected-access
                encrypted="AA==",
                aes_key="ignored",
            )

        self.assertEqual(decrypted, xml_text)

    async def test_get_verification_plain_and_aes_paths(self) -> None:
        logger = Mock()
        config = _make_config(aes_enabled=False)
        timestamp = "1700000000"
        nonce = "nonce-1"
        echostr = "echo-1"
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config.wechat.webhook.signature_token,
            timestamp=timestamp,
            nonce=nonce,
            encrypted=None,
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={
                    "timestamp": timestamp,
                    "nonce": nonce,
                    "echostr": echostr,
                    "signature": signature,
                }
            ),
        ):
            response = await webhook._handle_get_verification(  # pylint: disable=protected-access
                config_provider=lambda: config,
                logger_provider=lambda: logger,
            )
        self.assertEqual(response, echostr)

        config_aes = _make_config(aes_enabled=True)
        encrypted_echo = "ZW5jcnlwdGVkLWVjaG8="
        aes_signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config_aes.wechat.webhook.signature_token,
            timestamp=timestamp,
            nonce=nonce,
            encrypted=encrypted_echo,
        )
        with (
            patch.object(webhook, "_decrypt_wechat_payload", return_value="decrypted-echo"),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": timestamp,
                        "nonce": nonce,
                        "echostr": encrypted_echo,
                        "msg_signature": aes_signature,
                    }
                ),
            ),
        ):
            response = await webhook._handle_get_verification(  # pylint: disable=protected-access
                config_provider=lambda: config_aes,
                logger_provider=lambda: logger,
            )
        self.assertEqual(response, "decrypted-echo")

    async def test_get_verification_rejects_bad_signature_and_decrypt_failures(self) -> None:
        logger = Mock()
        config = _make_config(aes_enabled=False)
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "1",
                        "nonce": "2",
                        "echostr": "echo",
                        "signature": "bad",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_get_verification(  # pylint: disable=protected-access
                    config_provider=lambda: config,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 401)

        config_aes = _make_config(aes_enabled=True)
        encrypted_echo = "ZW5jcnlwdGVkLWVjaG8="
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config_aes.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted=encrypted_echo,
        )
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(webhook, "_decrypt_wechat_payload", side_effect=ValueError("bad")),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "1",
                        "nonce": "2",
                        "echostr": encrypted_echo,
                        "msg_signature": signature,
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_get_verification(  # pylint: disable=protected-access
                    config_provider=lambda: config_aes,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "1",
                        "nonce": "2",
                        "echostr": "echo",
                        "signature": "sig",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_get_verification(  # pylint: disable=protected-access
                    config_provider=lambda: SimpleNamespace(),
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_get_verification_signature_edge_cases(self) -> None:
        logger = Mock()
        config_aes = _make_config(aes_enabled=True)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "1",
                        "nonce": "2",
                        "echostr": "encrypted-echo",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_get_verification(  # pylint: disable=protected-access
                    config_provider=lambda: config_aes,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "1",
                        "nonce": "2",
                        "echostr": "encrypted-echo",
                        "msg_signature": "bad",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_get_verification(  # pylint: disable=protected-access
                    config_provider=lambda: config_aes,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 401)

        config_plain = _make_config(aes_enabled=False)
        msg_signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config_plain.wechat.webhook.signature_token,
            timestamp="3",
            nonce="4",
            encrypted=None,
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={
                    "timestamp": "3",
                    "nonce": "4",
                    "echostr": "echo-from-msg-signature",
                    "msg_signature": msg_signature,
                }
            ),
        ):
            response = await webhook._handle_get_verification(  # pylint: disable=protected-access
                config_provider=lambda: config_plain,
                logger_provider=lambda: logger,
            )
        self.assertEqual(response, "echo-from-msg-signature")

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "3",
                        "nonce": "4",
                        "echostr": "echo",
                    }
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_get_verification(  # pylint: disable=protected-access
                    config_provider=lambda: config_plain,
                    logger_provider=lambda: logger,
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_post_payload_plain_and_encrypted_paths(self) -> None:
        logger = Mock()
        config = _make_config(aes_enabled=False)
        body_xml = (
            "<xml>"
            "<FromUserName>user-1</FromUserName>"
            "<MsgType>text</MsgType>"
            "<Content>hello</Content>"
            "<MsgId>1</MsgId>"
            "</xml>"
        )
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted=None,
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=body_xml.encode("utf-8")),
            ),
        ):
            payload = await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                config=config,
                logger=logger,
            )
        self.assertEqual(payload["MsgType"], "text")
        self.assertIn("_received_at", payload)

        config_aes = _make_config(aes_enabled=True)
        outer_xml = "<xml><Encrypt>encrypted-body</Encrypt></xml>"
        msg_signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config_aes.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted="encrypted-body",
        )
        with (
            patch.object(
                webhook,
                "_decrypt_wechat_payload",
                return_value=body_xml,
            ),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "msg_signature": msg_signature},
                    get_data=AsyncMock(return_value=outer_xml.encode("utf-8")),
                ),
            ),
        ):
            payload = await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                config=config_aes,
                logger=logger,
            )
        self.assertEqual(payload["FromUserName"], "user-1")

    async def test_post_payload_rejects_malformed_body_and_missing_signature(self) -> None:
        logger = Mock()
        config = _make_config(aes_enabled=False)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "signature": "sig"},
                    get_data=AsyncMock(return_value=b"<xml><broken"),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_post_payload_additional_reject_paths(self) -> None:
        logger = Mock()
        config_plain = _make_config(aes_enabled=False)
        config_aes = _make_config(aes_enabled=True)
        outer_xml = "<xml><Encrypt>encrypted-body</Encrypt></xml>"

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2"},
                    get_data=AsyncMock(return_value=outer_xml.encode("utf-8")),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_aes,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={
                        "timestamp": "1",
                        "nonce": "2",
                        "msg_signature": "bad-signature",
                    },
                    get_data=AsyncMock(return_value=outer_xml.encode("utf-8")),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_aes,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 401)

        valid_sig = webhook._compute_signature(  # pylint: disable=protected-access
            token=config_aes.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted="encrypted-body",
        )
        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(webhook, "_decrypt_wechat_payload", side_effect=ValueError("bad")),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "msg_signature": valid_sig},
                    get_data=AsyncMock(return_value=outer_xml.encode("utf-8")),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_aes,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "msg_signature": "sig"},
                    get_data=AsyncMock(
                        return_value=b"<xml><MsgType>text</MsgType></xml>"
                    ),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_aes,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "signature": "bad"},
                    get_data=AsyncMock(
                        return_value=b"<xml><MsgType>text</MsgType></xml>"
                    ),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_plain,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 401)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(webhook, "_decrypt_wechat_payload", return_value="<xml><broken"),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "msg_signature": valid_sig},
                    get_data=AsyncMock(return_value=outer_xml.encode("utf-8")),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_aes,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 400)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2"},
                    get_data=AsyncMock(return_value=b"<xml><MsgType>text</MsgType></xml>"),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=config_plain,
                    logger=logger,
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_post_payload_rejects_missing_configuration_and_plaintext_for_aes_profile(
        self,
    ) -> None:
        logger = Mock()
        body_xml = b"<xml><MsgType>text</MsgType></xml>"
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token="signature-token-1",
            timestamp="1",
            nonce="2",
            encrypted=None,
        )

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "signature": signature},
                    get_data=AsyncMock(return_value=body_xml),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=SimpleNamespace(),
                    logger=logger,
                    path_token="path-token-1",
                )
            self.assertEqual(ex.exception.code, 500)

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "request",
                new=SimpleNamespace(
                    args={"timestamp": "1", "nonce": "2", "signature": signature},
                    get_data=AsyncMock(return_value=body_xml),
                ),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._resolve_inbound_payload_or_abort(  # pylint: disable=protected-access
                    config=_make_multi_profile_config(aes_enabled=True),
                    logger=logger,
                    path_token="path-token-1",
                )
            self.assertEqual(ex.exception.code, 400)

    async def test_official_account_event_endpoint_dispatches_ipc(self) -> None:
        endpoint = unwrap(webhook.wechat_official_account_event)
        logger = Mock()
        config = _make_config(aes_enabled=False)
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="wechat",
                    command="wechat_official_account_event",
                    expected_handlers=1,
                    received=1,
                    duration_ms=1,
                    results=[],
                    errors=[],
                )
            )
        )
        body_xml = (
            "<xml>"
            "<FromUserName>user-1</FromUserName>"
            "<MsgType>text</MsgType>"
            "<Content>hello</Content>"
            "<MsgId>1</MsgId>"
            "</xml>"
        )
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted=None,
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=body_xml.encode("utf-8")),
            ),
        ):
            response = await endpoint(
                path_token="path-token",
                config_provider=lambda: config,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, "success")
        request_payload = ipc_service.handle_ipc_request.await_args.args[0]
        self.assertEqual(request_payload.platform, "wechat")
        self.assertEqual(request_payload.command, "wechat_official_account_event")
        self.assertEqual(request_payload.data["provider"], "official_account")

    async def test_wecom_event_endpoint_logs_ipc_errors_and_returns_success(self) -> None:
        endpoint = unwrap(webhook.wechat_wecom_event)
        logger = Mock()
        config = _make_config(aes_enabled=False)
        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(
                return_value=IPCAggregateResult(
                    platform="wechat",
                    command="wechat_wecom_event",
                    expected_handlers=1,
                    received=1,
                    duration_ms=1,
                    results=[],
                    errors=[
                        IPCAggregateError(
                            code="timeout",
                            error="Timeout waiting for IPC handler response.",
                            handler="X",
                        )
                    ],
                )
            )
        )
        body_xml = (
            "<xml>"
            "<FromUserName>user-1</FromUserName>"
            "<MsgType>text</MsgType>"
            "<Content>hello</Content>"
            "<MsgId>1</MsgId>"
            "</xml>"
        )
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted=None,
        )
        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(
                args={"timestamp": "1", "nonce": "2", "signature": signature},
                get_data=AsyncMock(return_value=body_xml.encode("utf-8")),
            ),
        ):
            response = await endpoint(
                path_token="path-token",
                config_provider=lambda: config,
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, "success")
        logger.warning.assert_called_once()

    async def test_handle_post_event_stages_ingress_entries_when_ipc_provider_is_absent(
        self,
    ) -> None:
        logger = Mock()
        ingress_service = SimpleNamespace(stage=AsyncMock())
        entries = [object()]

        with (
            patch.object(
                webhook,
                "_resolve_inbound_payload_or_abort",
                new=AsyncMock(return_value={"MsgType": "text"}),
            ),
            patch.object(
                webhook,
                "extract_wechat_stage_entries",
                new=AsyncMock(return_value=entries),
            ) as extractor,
        ):
            response = await webhook._handle_post_event(  # pylint: disable=protected-access
                path_token="path-token",
                provider="official_account",
                command="wechat_official_account_event",
                config_provider=lambda: _make_config(aes_enabled=False),
                ipc_provider=None,
                ingress_provider=lambda: ingress_service,
                relational_storage_gateway_provider=lambda: "rsg",
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, "success")
        extractor.assert_awaited_once()
        ingress_service.stage.assert_awaited_once_with(entries)

    async def test_handle_post_event_aborts_when_ingress_staging_fails(self) -> None:
        logger = Mock()

        with (
            patch.object(webhook, "abort", side_effect=_abort_raiser),
            patch.object(
                webhook,
                "_resolve_inbound_payload_or_abort",
                new=AsyncMock(return_value={"MsgType": "text"}),
            ),
            patch.object(
                webhook,
                "extract_wechat_stage_entries",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            with self.assertRaises(_AbortCalled) as ex:
                await webhook._handle_post_event(  # pylint: disable=protected-access
                    path_token="path-token",
                    provider="official_account",
                    command="wechat_official_account_event",
                    config_provider=lambda: _make_config(aes_enabled=False),
                    ipc_provider=None,
                    ingress_provider=lambda: SimpleNamespace(stage=AsyncMock()),
                    relational_storage_gateway_provider=lambda: "rsg",
                    logger_provider=lambda: logger,
                )

        self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once()

    async def test_get_subscription_endpoints_invoke_verification_helper(self) -> None:
        official_endpoint = unwrap(webhook.wechat_official_account_subscription)
        wecom_endpoint = unwrap(webhook.wechat_wecom_subscription)

        config = _make_config(aes_enabled=False)
        logger = Mock()
        signature = webhook._compute_signature(  # pylint: disable=protected-access
            token=config.wechat.webhook.signature_token,
            timestamp="1",
            nonce="2",
            encrypted=None,
        )
        request_obj = SimpleNamespace(
            args={
                "timestamp": "1",
                "nonce": "2",
                "echostr": "echo-1",
                "signature": signature,
            }
        )
        with patch.object(webhook, "request", new=request_obj):
            official_response = await official_endpoint(
                path_token="path-token",
                config_provider=lambda: config,
                logger_provider=lambda: logger,
            )
        self.assertEqual(official_response, "echo-1")

        with patch.object(webhook, "request", new=request_obj):
            wecom_response = await wecom_endpoint(
                path_token="path-token",
                config_provider=lambda: config,
                logger_provider=lambda: logger,
            )
        self.assertEqual(wecom_response, "echo-1")
