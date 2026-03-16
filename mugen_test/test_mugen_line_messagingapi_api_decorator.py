"""Unit tests for mugen.core.plugin.line.messagingapi.api.decorator."""

from __future__ import annotations

import base64
import hashlib
import hmac
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.line.messagingapi.api import decorator as line_decorator


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(*, platforms: list[str] | None = None, secret: str = "line-secret"):
    return SimpleNamespace(
        mugen=SimpleNamespace(platforms=list(platforms or ["line"])),
        line=SimpleNamespace(
            channel=SimpleNamespace(secret=secret),
        ),
    )


def _make_service(
    *,
    path_token: str | None = "path-token",
    secret: str = "line-secret",
    build_raises: BaseException | None = None,
):
    client_profile = (
        None
        if path_token is None
        else SimpleNamespace(id="cp-1", profile_key="line-a")
    )
    service = Mock()
    service.resolve_active_by_identifier = AsyncMock(return_value=client_profile)
    if build_raises is not None:
        service.build_runtime_config = AsyncMock(side_effect=build_raises)
    else:
        service.build_runtime_config = AsyncMock(
            return_value=SimpleNamespace(
                line=SimpleNamespace(
                    channel=SimpleNamespace(secret=secret),
                )
            )
        )
    return service


class TestMugenLineMessagingapiDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform, path-token, and signature decorators."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
        )
        with patch.object(line_decorator.di, "container", new=container):
            self.assertEqual(line_decorator._config_provider(), "cfg")
            self.assertEqual(line_decorator._logger_provider(), "logger")
            service = line_decorator._client_profile_service()
            self.assertIsNotNone(service)

        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
        )
        with patch.object(line_decorator.di, "container", new=container):
            self.assertIsNone(line_decorator._client_profile_service())

        self.assertTrue(callable(line_decorator.line_platform_required()))
        self.assertTrue(callable(line_decorator.line_webhook_path_token_required()))
        self.assertTrue(callable(line_decorator.line_webhook_signature_required()))

    async def test_line_platform_required_paths(self) -> None:
        logger = Mock()

        async def _ok_handler(**_kwargs):
            return {"ok": True}

        with patch.object(line_decorator, "abort", side_effect=_abort_raiser):
            guarded = line_decorator.line_platform_required(
                _ok_handler,
                config_provider=lambda: _make_config(platforms=["matrix"]),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once_with("LINE platform not enabled.")

        logger = Mock()
        with patch.object(line_decorator, "abort", side_effect=_abort_raiser):
            guarded = line_decorator.line_platform_required(
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

        guarded = line_decorator.line_platform_required(
            _ok_handler,
            config_provider=lambda: _make_config(platforms=["line", "matrix"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

    async def test_line_webhook_path_token_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(line_decorator, "_client_profile_service", return_value=_make_service()),
        ):
            guarded = line_decorator.line_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("LINE webhook path token missing.")

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(line_decorator, "_client_profile_service", return_value=None),
        ):
            guarded = line_decorator.line_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "LINE webhook path token configuration missing."
            )

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(path_token=None),
            ),
        ):
            guarded = line_decorator.line_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="bad")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "LINE webhook path token verification failed."
            )

        failing_service = _make_service()
        failing_service.resolve_active_by_identifier = AsyncMock(
            side_effect=RuntimeError("db-down")
        )
        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=failing_service,
            ),
        ):
            guarded = line_decorator.line_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "LINE webhook path token configuration missing."
            )

        guarded = line_decorator.line_webhook_path_token_required(
            _ok_handler,
            config_provider=lambda: _make_config(),
            logger_provider=lambda: Mock(),
        )
        with patch.object(
            line_decorator,
            "_client_profile_service",
            return_value=_make_service(),
        ):
            self.assertEqual(await guarded(path_token="path-token"), {"ok": True})

    async def test_line_webhook_signature_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        body = b'{"events":[]}'
        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(line_decorator, "_client_profile_service", return_value=None),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "LINE channel secret configuration missing."
            )

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("LINE webhook path token missing.")

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(path_token=None),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "LINE webhook path token verification failed."
            )

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "request",
                new=SimpleNamespace(headers={}, get_data=AsyncMock(return_value=body)),
            ),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "LINE webhook signature header missing."
            )

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Line-Signature": "invalid"},
                    get_data=AsyncMock(return_value=body),
                ),
            ),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(secret="secret"),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(secret="secret"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "LINE webhook signature verification failed."
            )

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(build_raises=RuntimeError("bad config")),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(secret="secret"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "LINE channel secret configuration missing."
            )

        secret = "secret"
        signature = base64.b64encode(
            hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
        with (
            patch.object(
                line_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Line-Signature": signature},
                    get_data=AsyncMock(return_value=body),
                ),
            ),
            patch.object(
                line_decorator,
                "_client_profile_service",
                return_value=_make_service(secret=secret),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(secret=secret),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(path_token="path-token"), {"ok": True})
