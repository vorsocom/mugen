"""Unit tests for DI shutdown lifecycle helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core import di


class _AwaitableNoop:
    def __await__(self):
        if False:
            yield
        return None


class _AwaitableBoom:
    def __await__(self):
        if False:
            yield
        raise RuntimeError("await failed")


class _ProviderWithClose:
    def __init__(
        self,
        *,
        raises: Exception | None = None,
        awaitable: object | None = None,
    ):
        self._raises = raises
        self._awaitable = awaitable

    def close(self):
        if self._raises is not None:
            raise self._raises
        return self._awaitable


class _ProviderWithAClose:
    def __init__(
        self,
        *,
        raises: Exception | None = None,
        awaitable: object | None = None,
    ):
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


class TestMugenDIShutdownLifecycleSync(unittest.TestCase):
    """Covers sync wrapper behavior for shutdown helpers."""

    def test_shutdown_provider_sync_noop_and_run_failure(self) -> None:
        logger = Mock()
        di._shutdown_provider("none", None, logger)  # pylint: disable=protected-access

        def _raise_run_error(awaitable):
            awaitable.close()
            raise RuntimeError("boom")

        with patch("mugen.core.di.asyncio.run", side_effect=_raise_run_error):
            di._shutdown_provider(  # pylint: disable=protected-access
                "bad-run",
                _ProviderWithClose(awaitable=_AwaitableNoop()),
                logger,
            )
        self.assertIn("Failed to shutdown provider", logger.warning.call_args.args[0])

    def test_shutdown_provider_sync_raises_when_running_loop(self) -> None:
        logger = Mock()
        with patch("mugen.core.di.asyncio.get_running_loop", return_value=object()):
            with self.assertRaises(RuntimeError):
                di._shutdown_provider(  # pylint: disable=protected-access
                    "running-loop",
                    _ProviderWithClose(awaitable=_AwaitableNoop()),
                    logger,
                )
        logger.warning.assert_not_called()

    def test_shutdown_injector_sync_raises_when_running_loop(self) -> None:
        logger = Mock()
        injector = SimpleNamespace(logging_gateway=logger)
        with patch("mugen.core.di.asyncio.get_running_loop", return_value=object()):
            with self.assertRaises(RuntimeError):
                di._shutdown_injector(injector)  # pylint: disable=protected-access
        logger.warning.assert_not_called()

    def test_shutdown_container_delegates_to_proxy(self) -> None:
        with patch.object(di._ContainerProxy, "shutdown") as shutdown_mock:  # pylint: disable=protected-access
            di.shutdown_container()
        shutdown_mock.assert_called_once_with()

    def test_container_proxy_setattr_routes_to_built_injector(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        proxy._injector = SimpleNamespace(custom=None)  # pylint: disable=protected-access
        proxy.custom = "value"
        self.assertEqual(proxy.build().custom, "value")


class TestMugenDIShutdownLifecycleAsync(unittest.IsolatedAsyncioTestCase):
    """Covers async deterministic provider cleanup behavior."""

    async def test_shutdown_provider_async_noop_for_none_provider(self) -> None:
        logger = Mock()
        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "none",
            None,
            logger,
        )
        logger.warning.assert_not_called()

    async def test_shutdown_provider_async_error_paths(self) -> None:
        logger = Mock()

        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "bad-close",
            _ProviderWithClose(raises=RuntimeError("close failed")),
            logger,
        )
        self.assertIn("Failed to close provider", logger.warning.call_args.args[0])

        logger.reset_mock()
        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "bad-aclose",
            _ProviderWithAClose(raises=RuntimeError("aclose failed")),
            logger,
        )
        self.assertIn("Failed to invoke provider aclose", logger.warning.call_args.args[0])

        logger.reset_mock()
        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "await-fail",
            _ProviderWithClose(awaitable=_AwaitableBoom()),
            logger,
        )
        self.assertIn("Failed to await provider close", logger.warning.call_args.args[0])

        logger.reset_mock()
        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "await-fail-aclose",
            _ProviderWithAClose(awaitable=_AwaitableBoom()),
            logger,
        )
        self.assertIn("Failed to await provider aclose", logger.warning.call_args.args[0])

    async def test_shutdown_provider_async_handles_non_awaitable_close_result(self) -> None:
        logger = Mock()
        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "non-awaitable",
            _ProviderWithClose(awaitable=None),
            logger,
        )
        logger.warning.assert_not_called()

    async def test_shutdown_provider_closes_awaitable_success(self) -> None:
        logger = Mock()
        closed = {"value": False}

        async def _close():
            closed["value"] = True

        await di._shutdown_provider_async(  # pylint: disable=protected-access
            "async-close",
            _ProviderWithClose(awaitable=_close()),
            logger,
        )
        self.assertTrue(closed["value"])

    async def test_shutdown_injector_async_handles_duplicates_and_ext_services(self) -> None:
        logger = Mock()
        shared_provider = object()
        unique_service = object()
        injector = SimpleNamespace(
            logging_gateway=logger,
            completion_gateway=shared_provider,
            keyval_storage_gateway=shared_provider,
            ext_services={
                "shared": shared_provider,
                "unique": unique_service,
            },
        )

        with patch("mugen.core.di._shutdown_provider_async", new=AsyncMock()) as shutdown_mock:
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        calls_with_shared = [
            call
            for call in shutdown_mock.call_args_list
            if call.args[1] is shared_provider
        ]
        calls_with_unique = [
            call
            for call in shutdown_mock.call_args_list
            if call.args[0] == "ext_service:unique"
        ]
        self.assertEqual(len(calls_with_shared), 1)
        self.assertEqual(len(calls_with_unique), 1)
        self.assertIsNone(injector.completion_gateway)
        self.assertIsNone(injector.keyval_storage_gateway)

    async def test_shutdown_injector_async_handles_bad_ext_services(self) -> None:
        with patch("mugen.core.di._shutdown_provider_async", new=AsyncMock()) as shutdown_mock:
            await di._shutdown_injector_async(_ExtServicesBoom())  # pylint: disable=protected-access
        shutdown_mock.assert_not_called()

    async def test_shutdown_container_async_delegates_to_proxy(self) -> None:
        with patch.object(
            di._ContainerProxy,  # pylint: disable=protected-access
            "shutdown_async",
            new=AsyncMock(),
        ) as shutdown_mock:
            await di.shutdown_container_async()
        shutdown_mock.assert_awaited_once_with()
