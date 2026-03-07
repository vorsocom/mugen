"""Unit tests for mugen.core.plugin.whatsapp.wacapi.api.decorator."""

import hashlib
import hmac
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.whatsapp.wacapi.api import decorator as whatsapp_decorator
from mugen.core.utility.platform_runtime_profile import build_config_namespace


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(
    *,
    platforms: list[str] | None = None,
    verify_ip: bool = False,
    trust_forwarded_for: bool = False,
    basedir: str = "",
    allow_file: str = "",
    app_secret: str = "app-secret",
):
    return SimpleNamespace(
        basedir=basedir,
        mugen=SimpleNamespace(platforms=list(platforms or ["whatsapp"])),
        whatsapp=SimpleNamespace(
            app=SimpleNamespace(secret=app_secret),
            servers=SimpleNamespace(
                allowed=allow_file,
                verify_ip=verify_ip,
                trust_forwarded_for=trust_forwarded_for,
            ),
        ),
    )


def _make_multi_profile_config(*, app_secret: str = "app-secret-1") -> SimpleNamespace:
    return build_config_namespace(
        {
            "whatsapp": {
                "profiles": [
                    {
                        "key": "default",
                        "business": {"phone_number_id": "123456789"},
                        "app": {"secret": app_secret},
                    }
                ]
            }
        }
    )


class TestMugenWhatsAppWacapiDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform, signature, and IP allow-list decorators."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
        )
        with patch.object(whatsapp_decorator.di, "container", new=container):
            self.assertEqual(whatsapp_decorator._config_provider(), "cfg")
            self.assertEqual(whatsapp_decorator._logger_provider(), "logger")

    async def test_extract_phone_number_id_handles_missing_shapes_and_success(self) -> None:
        self.assertIsNone(whatsapp_decorator._extract_phone_number_id(None))
        self.assertIsNone(whatsapp_decorator._extract_phone_number_id({}))
        self.assertIsNone(
            whatsapp_decorator._extract_phone_number_id({"entry": ["bad-entry"]})
        )
        self.assertIsNone(whatsapp_decorator._extract_phone_number_id({"entry": [{}]}))
        self.assertIsNone(
            whatsapp_decorator._extract_phone_number_id(
                {"entry": [{"changes": ["bad-change"]}]}
            )
        )
        self.assertIsNone(
            whatsapp_decorator._extract_phone_number_id(
                {"entry": [{"changes": [{"value": {"metadata": {}}}]}]}
            )
        )
        self.assertIsNone(
            whatsapp_decorator._extract_phone_number_id(
                {"entry": [{"changes": [{"value": {"metadata": "bad-metadata"}}]}]}
            )
        )
        self.assertEqual(
            whatsapp_decorator._extract_phone_number_id(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "metadata": {
                                            "phone_number_id": " 123456789 ",
                                        }
                                    }
                                }
                            ]
                        }
                    ]
                }
            ),
            "123456789",
        )

    async def test_whatsapp_platform_required_paths(self) -> None:
        logger = Mock()

        async def _ok_handler():
            return {"ok": True}

        with patch.object(
            whatsapp_decorator, "abort", side_effect=_abort_raiser
        ) as abort_mock:
            guarded = whatsapp_decorator.whatsapp_platform_required(
                _ok_handler,
                config_provider=lambda: _make_config(platforms=["matrix"]),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once_with("WhatsApp platform not enabled.")
            abort_mock.assert_called_once_with(501)

        logger = Mock()
        with patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser):
            guarded = whatsapp_decorator.whatsapp_platform_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Could not get platform configuration."
            )

        guarded = whatsapp_decorator.whatsapp_platform_required(
            _ok_handler,
            config_provider=lambda: _make_config(platforms=["whatsapp", "matrix"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        guarded_factory = whatsapp_decorator.whatsapp_platform_required(
            config_provider=lambda: _make_config(platforms=["whatsapp"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

    async def test_whatsapp_request_signature_verification_required_paths(self) -> None:
        logger = Mock()
        body = b'{"entry":[{"id":"1"}]}'

        async def _ok_handler():
            return {"ok": True}

        with patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser):
            guarded = (
                whatsapp_decorator.whatsapp_request_signature_verification_required(
                    _ok_handler,
                    config_provider=lambda: SimpleNamespace(whatsapp=SimpleNamespace()),
                    logger_provider=lambda: logger,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("WhatsApp app secret not found.")

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(headers={}, get_data=AsyncMock(return_value=body)),
            ),
        ):
            guarded = (
                whatsapp_decorator.whatsapp_request_signature_verification_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(),
                    logger_provider=lambda: logger,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("Could not get request hash.")

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Hub-Signature-256": "sha256=deadbeef"},
                    get_data=AsyncMock(return_value=body),
                ),
            ),
        ):
            guarded = (
                whatsapp_decorator.whatsapp_request_signature_verification_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(app_secret="secret"),
                    logger_provider=lambda: logger,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with("API call unauthorized.")

        app_secret = "secret"
        digest = hmac.new(app_secret.encode("utf8"), body, hashlib.sha256).hexdigest()
        with patch.object(
            whatsapp_decorator,
            "request",
            new=SimpleNamespace(
                headers={"X-Hub-Signature-256": f"sha256={digest}"},
                get_data=AsyncMock(return_value=body),
            ),
        ):
            guarded = (
                whatsapp_decorator.whatsapp_request_signature_verification_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(app_secret=app_secret),
                    logger_provider=lambda: Mock(),
                )
            )
            self.assertEqual(await guarded(), {"ok": True})

            guarded_factory = (
                whatsapp_decorator.whatsapp_request_signature_verification_required(
                    config_provider=lambda: _make_config(app_secret=app_secret),
                    logger_provider=lambda: Mock(),
                )
            )
            self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

        logger = Mock()
        with patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser):
            guarded = whatsapp_decorator.whatsapp_request_signature_verification_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with patch.object(
                whatsapp_decorator,
                "identifier_configured_for_platform",
                side_effect=RuntimeError("bad config"),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("WhatsApp app secret not found.")

        profiled_body = (
            b'{"entry":[{"changes":[{"value":{"metadata":{"phone_number_id":"123456789"}}}]}]}'
        )
        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Hub-Signature-256": "sha256=deadbeef"},
                    get_data=AsyncMock(return_value=b"not-json"),
                ),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_request_signature_verification_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with(
                "Could not parse WhatsApp webhook payload."
            )

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Hub-Signature-256": "sha256=deadbeef"},
                    get_data=AsyncMock(return_value=b'{"entry":[{"changes":[{}]}]}'),
                ),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_request_signature_verification_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with(
                "WhatsApp phone_number_id missing from webhook payload."
            )

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Hub-Signature-256": "sha256=deadbeef"},
                    get_data=AsyncMock(return_value=profiled_body),
                ),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_request_signature_verification_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with patch.object(
                whatsapp_decorator,
                "find_platform_runtime_profile_key",
                return_value=None,
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "WhatsApp phone_number_id verification failed."
            )

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Hub-Signature-256": "sha256=deadbeef"},
                    get_data=AsyncMock(return_value=profiled_body),
                ),
            ),
            patch.object(
                whatsapp_decorator,
                "get_platform_profile_section",
                side_effect=KeyError("missing"),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_request_signature_verification_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("WhatsApp app secret not found.")

        profiled_secret = "profile-secret"
        profiled_digest = hmac.new(
            profiled_secret.encode("utf8"),
            profiled_body,
            hashlib.sha256,
        ).hexdigest()
        with patch.object(
            whatsapp_decorator,
            "request",
            new=SimpleNamespace(
                headers={"X-Hub-Signature-256": f"sha256={profiled_digest}"},
                get_data=AsyncMock(return_value=profiled_body),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_request_signature_verification_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(
                    app_secret=profiled_secret
                ),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(), {"ok": True})

    async def test_whatsapp_server_ip_allow_list_required_paths(self) -> None:
        async def _ok_handler():
            return {"ok": True}

        guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
            _ok_handler,
            config_provider=lambda: _make_config(
                verify_ip=False,
                basedir="/tmp",
                allow_file="missing.txt",
            ),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(whatsapp=SimpleNamespace()),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once_with("WhatsApp IP verification configuration missing.")

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(remote_addr="10.0.0.10", headers={}),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(
                    whatsapp=SimpleNamespace(
                        servers=SimpleNamespace(verify_ip="yes")
                    )
                ),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
        logger.error.assert_called_once_with(
            "WhatsApp IP verification configuration invalid."
        )

        guarded_factory = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
            config_provider=lambda: _make_config(verify_ip=False),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

        logger = Mock()
        with (
            patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    remote_addr=None,
                    headers={},
                ),
            ),
        ):
            guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                _ok_handler,
                config_provider=lambda: _make_config(
                    verify_ip=True,
                    basedir="/tmp",
                    allow_file="missing.txt",
                ),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "WhatsApp servers allow list not found."
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            allow_file = "allow.list.txt"
            with open(f"{tmpdir}/{allow_file}", "w", encoding="utf8") as file:
                file.write("10.0.0.0/24\n")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(remote_addr=None, headers={}),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 400)
                logger.error.assert_called_once_with(
                    "Remote address could not be determined."
                )

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(
                        remote_addr="not-an-ip",
                        headers={},
                    ),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 400)
                logger.error.assert_called_once_with("Remote address is invalid.")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(
                        remote_addr="203.0.113.10",
                        headers={},
                    ),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 403)
                logger.error.assert_called_once_with(
                    "Remote address not in allow list."
                )

            with patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    remote_addr="10.0.0.10",
                    headers={},
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: Mock(),
                )
                self.assertEqual(await guarded(), {"ok": True})

            with patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    remote_addr="10.0.0.10",
                    headers={"X-Forwarded-For": ""},
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        trust_forwarded_for=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: Mock(),
                )
                self.assertEqual(await guarded(), {"ok": True})

            with open(f"{tmpdir}/{allow_file}", "w", encoding="utf8") as file:
                file.write("bad-cidr\n")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(
                        remote_addr="10.0.0.10",
                        headers={},
                    ),
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: logger,
                )
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
                self.assertEqual(ex.exception.code, 500)
                logger.error.assert_called_once_with(
                    "Invalid CIDR entry in WhatsApp allow list."
                )

            with open(f"{tmpdir}/{allow_file}", "w", encoding="utf8") as file:
                file.write("10.0.0.0/24\n")

            with patch.object(
                whatsapp_decorator,
                "request",
                new=SimpleNamespace(
                    remote_addr="203.0.113.5",
                    headers={"X-Forwarded-For": "10.0.0.42, 203.0.113.1"},
                ),
            ):
                guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
                    _ok_handler,
                    config_provider=lambda: _make_config(
                        verify_ip=True,
                        trust_forwarded_for=True,
                        basedir=tmpdir,
                        allow_file=allow_file,
                    ),
                    logger_provider=lambda: Mock(),
                )
                self.assertEqual(await guarded(), {"ok": True})
