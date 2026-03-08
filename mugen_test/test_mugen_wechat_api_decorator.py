"""Unit tests for mugen.core.plugin.wechat.api.decorator."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.wechat.api import decorator as wechat_decorator


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(*, platforms: list[str] | None = None):
    return SimpleNamespace(
        mugen=SimpleNamespace(platforms=list(platforms or ["wechat"])),
        wechat=SimpleNamespace(),
    )


def _make_client_profile(*, path_token: str = "path-token-1") -> SimpleNamespace:
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000301",
        platform_key="wechat",
        path_token=path_token,
    )


def _make_runtime_config(*, provider: str = "official_account") -> SimpleNamespace:
    return SimpleNamespace(
        wechat=SimpleNamespace(provider=provider),
    )


class TestMugenWeChatDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform, path-token, and provider decorators."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            config="cfg",
            logging_gateway="logger",
        )
        with patch.object(wechat_decorator.di, "container", new=container):
            self.assertEqual(wechat_decorator._config_provider(), "cfg")
            self.assertEqual(wechat_decorator._logger_provider(), "logger")
            self.assertIsNone(wechat_decorator._client_profile_service())

        with patch.object(
            wechat_decorator,
            "MessagingClientProfileService",
            return_value="service",
        ) as service_cls:
            container = SimpleNamespace(
                config="cfg",
                logging_gateway="logger",
                relational_storage_gateway="rsg",
            )
            with patch.object(wechat_decorator.di, "container", new=container):
                self.assertEqual(wechat_decorator._client_profile_service(), "service")
        service_cls.assert_called_once_with(
            table="admin_messaging_client_profile",
            rsg="rsg",
        )

    async def test_wechat_platform_required_paths(self) -> None:
        logger = Mock()

        async def _ok_handler(**_kwargs):
            return {"ok": True}

        with patch.object(wechat_decorator, "abort", side_effect=_abort_raiser):
            guarded = wechat_decorator.wechat_platform_required(
                _ok_handler,
                config_provider=lambda: _make_config(platforms=["telegram"]),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once_with("WeChat platform not enabled.")

        logger = Mock()
        with patch.object(wechat_decorator, "abort", side_effect=_abort_raiser):
            guarded = wechat_decorator.wechat_platform_required(
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

        guarded = wechat_decorator.wechat_platform_required(
            _ok_handler,
            config_provider=lambda: _make_config(platforms=["wechat", "matrix"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        guarded_factory = wechat_decorator.wechat_platform_required(
            config_provider=lambda: _make_config(platforms=["wechat"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})

    async def test_wechat_webhook_path_token_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with patch.object(wechat_decorator, "abort", side_effect=_abort_raiser):
            guarded = wechat_decorator.wechat_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("WeChat webhook path token missing.")

        logger = Mock()
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=None,
            ),
        ):
            guarded = wechat_decorator.wechat_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="path")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "WeChat webhook path token configuration missing."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=None)
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="missing")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "WeChat webhook path token verification failed."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(side_effect=KeyError("missing"))
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with(
                "WeChat webhook path token configuration missing."
            )

        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            )
        )
        with patch.object(
            wechat_decorator,
            "_client_profile_service",
            return_value=service,
        ):
            guarded = wechat_decorator.wechat_webhook_path_token_required(
                _ok_handler,
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(await guarded(path_token="expected"), {"ok": True})

            guarded_factory = wechat_decorator.wechat_webhook_path_token_required(
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )
            self.assertEqual(
                await guarded_factory(_ok_handler)(path_token="expected"),
                {"ok": True},
            )

    async def test_wechat_provider_required_paths(self) -> None:
        async def _ok_handler(**_kwargs):
            return {"ok": True}

        logger = Mock()
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=None,
            ),
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "official_account",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )(_ok_handler)
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("WeChat provider configuration missing.")

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(provider="official_account")
            ),
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "wecom",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )(_ok_handler)
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once()

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(provider="official_account")
            ),
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "official_account",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )(_ok_handler)
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()
            self.assertEqual(ex.exception.code, 400)
            logger.error.assert_called_once_with("WeChat webhook path token missing.")

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(side_effect=KeyError("missing")),
            build_runtime_config=AsyncMock(),
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "official_account",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )(_ok_handler)
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("WeChat provider configuration missing.")

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(return_value=None),
            build_runtime_config=AsyncMock(),
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "official_account",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )(_ok_handler)
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="missing")
            self.assertEqual(ex.exception.code, 401)
            logger.error.assert_called_once_with(
                "WeChat webhook path token verification failed."
            )

        logger = Mock()
        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(side_effect=RuntimeError("bad config")),
        )
        with (
            patch.object(wechat_decorator, "abort", side_effect=_abort_raiser),
            patch.object(
                wechat_decorator,
                "_client_profile_service",
                return_value=service,
            ),
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "official_account",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: logger,
            )(_ok_handler)
            with self.assertRaises(_AbortCalled) as ex:
                await guarded(path_token="expected")
            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("WeChat provider configuration missing.")

        service = SimpleNamespace(
            resolve_active_by_identifier=AsyncMock(
                return_value=_make_client_profile(path_token="expected")
            ),
            build_runtime_config=AsyncMock(
                return_value=_make_runtime_config(provider="official_account")
            ),
        )
        with patch.object(
            wechat_decorator,
            "_client_profile_service",
            return_value=service,
        ):
            guarded = wechat_decorator.wechat_provider_required(
                "official_account",
                config_provider=lambda: _make_config(),
                logger_provider=lambda: Mock(),
            )(_ok_handler)
            self.assertEqual(await guarded(path_token="expected"), {"ok": True})
