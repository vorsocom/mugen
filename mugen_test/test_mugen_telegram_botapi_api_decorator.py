"""Unit tests for mugen.core.plugin.telegram.botapi.api.decorator."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.telegram.botapi.api import decorator as telegram_decorator


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(*, platforms: list[str] | None = None):
    return SimpleNamespace(
        mugen=SimpleNamespace(platforms=list(platforms or ["telegram"])),
        telegram=SimpleNamespace(),
    )


def _make_client_profile(*, path_token: str = "path-token-1") -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000201",
        platform_key="telegram",
        path_token=path_token,
    )


def _make_runtime_config(*, secret_token: str = "secret-token-1") -> SimpleNamespace:
    return SimpleNamespace(
        telegram=SimpleNamespace(
            webhook=SimpleNamespace(secret_token=secret_token),
        )
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
            self.assertIsNone(telegram_decorator._client_profile_service())

        with patch.object(
            telegram_decorator,
            "MessagingClientProfileService",
            return_value="service",
        ) as service_cls:
            container = SimpleNamespace(
                config="cfg",
                logging_gateway="logger",
                relational_storage_gateway="rsg",
            )
            with patch.object(telegram_decorator.di, "container", new=container):
                self.assertEqual(
                    telegram_decorator._client_profile_service(),
                    "service",
                )
        service_cls.assert_called_once_with(
            table="admin_messaging_client_profile",
            rsg="rsg",
        )

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
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=None,
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook path token configuration missing."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=None)
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="missing")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "Telegram webhook path token verification failed."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(side_effect=KeyError("missing"))
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook path token configuration missing."
            )

        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            )
        )
        with patch.object(
            telegram_decorator,
            "_client_profile_service",
            return_value=service,
        ):
            guarded = telegram_decorator.telegram_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(path_token="expected"), {"ok": True})
            service.resolve_active_by_identifier.assert_awaited_once_with(
                platform_key="telegram",
                identifier_type="path_token",
                identifier_value="expected",
            )

            guarded_factory = telegram_decorator.telegram_webhook_path_token_required(
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(
                await guarded_factory(_ok_handler)(path_token="expected"),
                {"ok": True},
            )

    async def test_telegram_webhook_secret_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=None,
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook secret configuration missing."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(secret_token="expected")
            ),
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("Telegram webhook path token missing.")

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(secret_token="expected")
            ),
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(headers={}),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with("Telegram webhook secret header missing.")

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(secret_token="expected")
            ),
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
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
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "Telegram webhook secret verification failed."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=None),
            build_runtime_config=AsyncMock(),
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Telegram-Bot-Api-Secret-Token": "expected"}
                ),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="missing")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "Telegram webhook path token verification failed."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(side_effect=KeyError("missing")),
        )
        with (
            patch.object(telegram_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Telegram-Bot-Api-Secret-Token": "expected"}
                ),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "Telegram webhook secret configuration missing."
            )

        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(secret_token="expected")
            ),
        )
        with (
            patch.object(
                telegram_decorator,
                "_client_profile_service",
                return_value=service,
            ),
            patch.object(
                telegram_decorator,
                "request",
                new=SimpleNamespace(
                    headers={"X-Telegram-Bot-Api-Secret-Token": "expected"}
                ),
            ),
        ):
            guarded = telegram_decorator.telegram_webhook_secret_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(path_token="expected"), {"ok": True})

            guarded_factory = telegram_decorator.telegram_webhook_secret_required(
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(
                await guarded_factory(_ok_handler)(path_token="expected"),
                {"ok": True},
            )
