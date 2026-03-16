"""Unit tests for mugen.core.plugin.web.api.decorator."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.plugin.web.api import decorator as web_decorator


class _AbortCalled(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def _abort_raiser(code: int, *_args, **_kwargs):
    raise _AbortCalled(code)


def _make_config(platforms: list[str] | None = None):
    return SimpleNamespace(
        mugen=SimpleNamespace(platforms=list(platforms or ["web"]))
    )


class TestMugenWebApiDecorator(unittest.IsolatedAsyncioTestCase):
    """Covers platform-required decorator branches for web endpoints."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(config="cfg", logging_gateway="logger")

        with patch.object(web_decorator.di, "container", new=container):
            self.assertEqual(web_decorator._config_provider(), "cfg")
            self.assertEqual(web_decorator._logger_provider(), "logger")

    async def test_web_platform_required_paths(self) -> None:
        async def _ok_handler():
            return {"ok": True}

        logger = Mock()
        with patch.object(web_decorator, "abort", side_effect=_abort_raiser):
            guarded = web_decorator.web_platform_required(
                _ok_handler,
                config_provider=lambda: _make_config(["matrix"]),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()

            self.assertEqual(ex.exception.code, 501)
            logger.error.assert_called_once_with("Web platform not enabled.")

        logger = Mock()
        with patch.object(web_decorator, "abort", side_effect=_abort_raiser):
            guarded = web_decorator.web_platform_required(
                _ok_handler,
                config_provider=lambda: SimpleNamespace(),
                logger_provider=lambda: logger,
            )
            with self.assertRaises(_AbortCalled) as ex:
                await guarded()

            self.assertEqual(ex.exception.code, 500)
            logger.error.assert_called_once_with("Could not get platform configuration.")

        guarded = web_decorator.web_platform_required(
            _ok_handler,
            config_provider=lambda: _make_config(["web", "matrix"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded(), {"ok": True})

        guarded_factory = web_decorator.web_platform_required(
            config_provider=lambda: _make_config(["web"]),
            logger_provider=lambda: Mock(),
        )
        self.assertEqual(await guarded_factory(_ok_handler)(), {"ok": True})
