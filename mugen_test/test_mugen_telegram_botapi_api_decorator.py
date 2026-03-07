"""Unit tests for mugen.core.plugin.telegram.botapi.api.decorator."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.plugin.telegram.botapi.api import decorator as telegram_decorator
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
    path_token: str = "path-token-1",
    secret_token: str = "secret-token-1",
):
    return SimpleNamespace(
        mugen=SimpleNamespace(platforms=list(platforms or ["telegram"])),
        telegram=SimpleNamespace(
            webhook=SimpleNamespace(
                path_token=path_token,
                secret_token=secret_token,
            )
        ),
    )


def _make_multi_profile_config() -> SimpleNamespace:
    return build_config_namespace(
        {
            "telegram": {
                "profiles": [
                    {
                        "key": "default",
                        "bot": {"token": "bot-token-1"},
                        "webhook": {
                            "path_token": "path-token-1",
                            "secret_token": "secret-token-1",
                        },
                    },
                    {
                        "key": "secondary",
                        "bot": {"token": "bot-token-2"},
                        "webhook": {
                            "path_token": "path-token-2",
                            "secret_token": "secret-token-2",
                        },
                    },
                ]
            }
        }
    )


class TestMugenTelegramBotapiDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform, path-token, and secret-header decorators."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
        )
        with patch.object(telegram_decorator.di, "container", new=container):
            self.assertEqual(telegram_decorator._config_provider(), "cfg")
            self.assertEqual(telegram_decorator._logger_provider(), "logger")

    async def test_telegram_platform_required_paths(self) -> None:
        logger = Mock()

        async def _ok_handler(**_kwargs):
            return {"ok": True}

        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_platform_required(
                _ok_handler,
                config_provider=lambda: _make_config(platforms=["matrix"]),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once_with("Telegram platform not enabled.")

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_platform_required(
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

        guarded = telegram_decorator.telegram_platform_required(
            _ok_handler,
            config_provider=lambda: _make_config(platforms=["telegram", "matrix"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        guarded_factory = telegram_decorator.telegram_platform_required(
            config_provider=lambda: _make_config(platforms=["telegram"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

    async def test_telegram_webhook_path_token_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("Telegram webhook path token missing.")

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(telegram=SimpleNamespace()),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook path token configuration missing."
            )

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(path_token="expected"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="bad")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "Telegram webhook path token verification failed."
            )

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(path_token="   "),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook path token configuration missing."
            )

        guarded = telegram_decorator.telegram_webhook_path_token_required(
            _ok_handler,
            config_provider=lambda: _make_config(path_token="expected"),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(path_token="expected"), {"ok": True})

        guarded_factory = telegram_decorator.telegram_webhook_path_token_required(
            config_provider=lambda: _make_config(path_token="expected"),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(
            await guarded_factory(_ok_handler)(path_token="expected"),
            {"ok": True},
        )

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(path_token="expected"),
                logger_provider=lambda: logger,
            )
            with patch.object(
                telegram_decorator,
                "identifier_configured_for_platform",
                side_effect=RuntimeError("bad config"),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook path token configuration missing."
            )

    async def test_telegram_webhook_secret_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(telegram=SimpleNamespace()),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook secret configuration missing."
            )

        logger = Mock()
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(headers={}),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(secret_token="expected"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with("Telegram webhook secret header missing.")

        logger = Mock()
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Telegram-Bot-Api-Secret-Token": "bad"}
                ),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(secret_token="expected"),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "Telegram webhook secret verification failed."
            )

        with patch.object(
            telegram_decorator,
            "request",
            new=SimpleNamespace(
                headers={"X-Telegram-Bot-Api-Secret-Token": "expected"}
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(secret_token="expected"),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(), {"ok": True})

            guarded_factory = telegram_decorator.telegram_webhook_secret_required(
                config_provider=lambda: _make_config(secret_token="expected"),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("Telegram webhook path token missing.")

        logger = Mock()
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Telegram-Bot-Api-Secret-Token": "secret-token-1"}
                ),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="missing-token")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "Telegram webhook path token verification failed."
            )

        logger = Mock()
        with patch.object(telegram_decorator, "abort", side_effect=_abort_raiser):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with patch.object(
                telegram_decorator,
                "identifier_configured_for_platform",
                side_effect=RuntimeError("bad config"),
            ):
                with self.assertRaises(_AbortCalled) as ex:
                    await guarded()
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook secret configuration missing."
            )

        logger = Mock()
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Telegram-Bot-Api-Secret-Token": "secret-token-1"}
                ),
            ),
            patch.object(
                telegram_decorator,
                "get_platform_profile_section",
                side_effect=KeyError("missing"),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_multi_profile_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path-token-1")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook secret configuration missing."
            )
