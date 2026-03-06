"""Unit tests for mugen.core.plugin.line.messagingapi.api.decorator."""

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


def _make_config(
    *,
    platforms: list[str] | None = None,
    path_token: str = "path-token-1",
    channel_secret: str = "line-secret-1",
):
    return SimpleNamespace(
        mugen=SimpleNamespace(platforms=list(platforms or ["line"])),
        line=SimpleNamespace(
            webhook=SimpleNamespace(path_token=path_token),
            channel=SimpleNamespace(secret=channel_secret),
        ),
    )


class TestMugenLineMessagingapiDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform, path-token, and signature decorators."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
        )
        with patch.object(line_decorator.di, "container", new=container):
            self.assertEqual(line_decorator._config_provider(), "cfg")
            self.assertEqual(line_decorator._logger_provider(), "logger")

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

        guarded_factory = line_decorator.line_platform_required(
            config_provider=lambda: _make_config(platforms=["line"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

    async def test_line_webhook_path_token_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with patch.object(line_decorator, "abort", side_effect=_abort_raiser):
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
        guarded = line_decorator.line_webhook_path_token_required(
            _ok_handler,
            config_provider=lambda: SimpleNamespace(line=SimpleNamespace()),
            logger_provider=lambda: logger,
        )
        self.assertEqual(await guarded(path_token="path"), {"ok": True})

        guarded = line_decorator.line_webhook_path_token_required(
            _ok_handler,
            config_provider=lambda: _make_config(path_token="expected"),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(path_token="bad"), {"ok": True})

        guarded_factory = line_decorator.line_webhook_path_token_required(
            config_provider=lambda: _make_config(path_token="expected"),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(
            await guarded_factory(_ok_handler)(path_token="any-token"),
            {"ok": True},
        )

    async def test_line_webhook_signature_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        body = b'{"events":[]}'

        logger = Mock()
        with patch.object(line_decorator, "abort", side_effect=_abort_raiser):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(line=SimpleNamespace()),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "LINE channel secret configuration missing."
            )

        logger = Mock()
        with (
            patch.object(line_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                line_decorator,
                "request",
                new=SimpleNamespace(headers={}, get_data=AsyncMock(return_value=body)),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(channel_secret="secret"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
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
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(channel_secret="secret"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "LINE webhook signature verification failed."
            )

        channel_secret = "secret"
        signature = base64.b64encode(
            hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
        ).decode("utf-8")
        with patch.object(
            line_decorator,
            "request",
            new=SimpleNamespace(
                headers={"X-Line-Signature": signature},
                get_data=AsyncMock(return_value=body),
            ),
        ):
            guarded = line_decorator.line_webhook_signature_required(
                _ok_handler,
                config_provider=lambda: _make_config(channel_secret=channel_secret),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(), {"ok": True})

            guarded_factory = line_decorator.line_webhook_signature_required(
                config_provider=lambda: _make_config(channel_secret=channel_secret),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})
