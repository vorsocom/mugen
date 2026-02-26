"""Unit tests for DI shutdown lifecycle helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core import di


class _AwaitableNoop:
    def __await__(self):
        if False:
            yield
        return None


class _ProviderWithClose:
    def __init__(self, *, raises: Exception | None = None, awaitable: object | None = None):
        self._raises = raises
        self._awaitable = awaitable

    def close(self):
        if self._raises is not None:
            raise self._raises
        return self._awaitable


class _ProviderWithAClose:
    def __init__(self, *, raises: Exception | None = None, awaitable: object | None = None):
        self._raises = raises
        self._awaitable = awaitable

    def aclose(self):
        if self._raises is not None:
            raise self._raises
        return self._awaitable


class _ExtServicesBoom:
    @property
    def ext_services(self):
        raise RuntimeError("boom")


class TestMugenDIShutdownLifecycle(unittest.TestCase):
    """Covers provider cleanup and container shutdown branches."""

    def test_shutdown_provider_noop_and_close_error(self) -> None:
        logger = Mock()
        di._shutdown_provider("none", None, logger)  # pylint: disable=protected-access

        di._shutdown_provider(  # pylint: disable=protected-access
            "bad-close",
            _ProviderWithClose(raises=RuntimeError("close failed")),
            logger,
        )
        logger.warning.assert_called_once()
        self.assertIn("Failed to close provider", logger.warning.call_args.args[0])

    def test_shutdown_provider_aclose_invoke_and_await_errors(self) -> None:
        logger = Mock()

        di._shutdown_provider(  # pylint: disable=protected-access
            "bad-aclose",
            _ProviderWithAClose(raises=RuntimeError("aclose failed")),
            logger,
        )
        self.assertIn("Failed to invoke provider aclose", logger.warning.call_args.args[0])

        logger.reset_mock()
        with patch("mugen.core.di.asyncio.run", side_effect=Exception("await failed")):
            di._shutdown_provider(  # pylint: disable=protected-access
                "await-fail",
                _ProviderWithClose(awaitable=_AwaitableNoop()),
                logger,
            )
        self.assertIn("Failed to await provider aclose", logger.warning.call_args.args[0])

    def test_shutdown_provider_runtimeerror_paths(self) -> None:
        logger = Mock()
        fake_loop = Mock()

        with (
            patch("mugen.core.di.asyncio.run", side_effect=RuntimeError("loop running")),
            patch("mugen.core.di.asyncio.get_running_loop", return_value=fake_loop),
        ):
            di._shutdown_provider(  # pylint: disable=protected-access
                "schedule-task",
                _ProviderWithClose(awaitable=_AwaitableNoop()),
                logger,
            )
        fake_loop.create_task.assert_called_once()

        logger.reset_mock()
        with (
            patch("mugen.core.di.asyncio.run", side_effect=RuntimeError("loop running")),
            patch(
                "mugen.core.di.asyncio.get_running_loop",
                side_effect=RuntimeError("no running loop"),
            ),
        ):
            di._shutdown_provider(  # pylint: disable=protected-access
                "no-loop",
                _ProviderWithClose(awaitable=_AwaitableNoop()),
                logger,
            )
        self.assertIn("no running loop exists", logger.warning.call_args.args[0])

    def test_shutdown_provider_non_awaitable_close_result(self) -> None:
        logger = Mock()
        provider = _ProviderWithClose(awaitable=None)

        with patch("mugen.core.di.asyncio.run") as run_mock:
            di._shutdown_provider("non-awaitable", provider, logger)  # pylint: disable=protected-access

        run_mock.assert_not_called()

    def test_shutdown_injector_handles_duplicates_and_bad_ext_services(self) -> None:
        logger = Mock()
        shared_provider = object()
        injector = SimpleNamespace(
            logging_gateway=logger,
            completion_gateway=shared_provider,
            keyval_storage_gateway=shared_provider,
        )

        with patch("mugen.core.di._shutdown_provider") as shutdown_provider:
            di._shutdown_injector(injector)  # pylint: disable=protected-access

        shared_calls = [
            call
            for call in shutdown_provider.call_args_list
            if call.args[1] is shared_provider
        ]
        self.assertEqual(len(shared_calls), 1)
        self.assertIsNone(injector.completion_gateway)
        self.assertIsNone(injector.keyval_storage_gateway)

        with patch("mugen.core.di._shutdown_provider") as shutdown_provider:
            di._shutdown_injector(_ExtServicesBoom())  # pylint: disable=protected-access
        shutdown_provider.assert_not_called()

    def test_shutdown_injector_ext_services_skip_seen_and_shutdown_unique(self) -> None:
        logger = Mock()
        shared_provider = object()
        unique_service = object()
        injector = SimpleNamespace(
            logging_gateway=logger,
            completion_gateway=shared_provider,
            ext_services={
                "shared": shared_provider,
                "unique": unique_service,
            },
        )

        with patch("mugen.core.di._shutdown_provider") as shutdown_provider:
            di._shutdown_injector(injector)  # pylint: disable=protected-access

        shared_calls = [
            call
            for call in shutdown_provider.call_args_list
            if call.args[1] is shared_provider
        ]
        unique_calls = [
            call
            for call in shutdown_provider.call_args_list
            if call.args[0] == "ext_service:unique"
        ]
        self.assertEqual(len(shared_calls), 1)
        self.assertEqual(len(unique_calls), 1)

    def test_shutdown_container_delegates_to_proxy(self) -> None:
        with patch.object(di._ContainerProxy, "shutdown") as shutdown_mock:  # pylint: disable=protected-access
            di.shutdown_container()
        shutdown_mock.assert_called_once_with()

    def test_container_proxy_setattr_routes_to_built_injector(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        proxy._injector = SimpleNamespace(custom=None)  # pylint: disable=protected-access
        proxy.custom = "value"
        self.assertEqual(proxy.build().custom, "value")

    def test_shutdown_provider_closes_awaitable_success(self) -> None:
        logger = Mock()
        closed = {"value": False}

        async def _close():
            closed["value"] = True

        di._shutdown_provider(  # pylint: disable=protected-access
            "async-close",
            _ProviderWithClose(awaitable=_close()),
            logger,
        )
        self.assertTrue(closed["value"])
