"""Unit tests for mugen.core.plugin.whatsapp.wacapi.api.decorator."""

import hashlib
import hmac
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.whatsapp.wacapi.api import decorator as whatsapp_decorator


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
            ),
        ),
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
        guarded = whatsapp_decorator.whatsapp_server_ip_allow_list_required(
            _ok_handler,
            config_provider=lambda: SimpleNamespace(whatsapp=SimpleNamespace()),
            logger_provider=lambda: logger,
        )
        self.assertEqual(await guarded(), {"ok": True})
        logger.error.assert_called_once_with(
            "WhatsApp ip verification requirement unknown."
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
                    access_route=["10.0.0.9"], remote_addr=None, headers={}
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
                    new=SimpleNamespace(access_route=[], remote_addr=None, headers={}),
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
                        access_route=["not-an-ip"],
                        remote_addr=None,
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
                        access_route=["203.0.113.10"],
                        remote_addr=None,
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
                    access_route=["10.0.0.10"],
                    remote_addr=None,
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

            with open(f"{tmpdir}/{allow_file}", "w", encoding="utf8") as file:
                file.write("bad-cidr\n")

            logger = Mock()
            with (
                patch.object(whatsapp_decorator, "abort", side_effect=_abort_raiser),
                patch.object(
                    whatsapp_decorator,
                    "request",
                    new=SimpleNamespace(
                        access_route=["10.0.0.10"],
                        remote_addr=None,
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
