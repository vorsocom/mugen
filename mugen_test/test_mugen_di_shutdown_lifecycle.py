"""Unit tests for DI shutdown lifecycle helpers."""

from __future__ import annotations

import asyncio
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
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            dict={
                "mugen": {
                    "runtime": {
                        "profile": "platform_full",
                        "provider_readiness_timeout_seconds": 15.0,
                        "provider_shutdown_timeout_seconds": 0.5,
                        "shutdown_timeout_seconds": 5.0,
                        "phase_b": {"startup_timeout_seconds": 30.0},
                    }
                }
            }
        )
        self.logging_gateway = Mock()

    @property
    def ext_services(self):
        raise RuntimeError("boom")


def _runtime_config_dict(
    *,
    provider_shutdown_timeout_seconds: object = 0.5,
    shutdown_timeout_seconds: object = 5.0,
) -> dict:
    return {
        "mugen": {
            "runtime": {
                "profile": "platform_full",
                "provider_readiness_timeout_seconds": 15.0,
                "provider_shutdown_timeout_seconds": provider_shutdown_timeout_seconds,
                "shutdown_timeout_seconds": shutdown_timeout_seconds,
                "phase_b": {"startup_timeout_seconds": 30.0},
            }
        }
    }


class TestMugenDIShutdownLifecycleSync(unittest.TestCase):
    """Covers sync wrapper behavior for shutdown helpers."""

    def test_shutdown_provider_sync_noop_and_run_failure(self) -> None:
        logger = Mock()
        di._shutdown_provider("none", None, logger)  # pylint: disable=protected-access

        def _raise_run_error(awaitable):
            awaitable.close()
            raise RuntimeError("boom")

        with patch("mugen.core.di.asyncio.run", side_effect=_raise_run_error):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                di._shutdown_provider(  # pylint: disable=protected-access
                    "bad-run",
                    _ProviderWithClose(awaitable=_AwaitableNoop()),
                    logger,
                )

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

    def test_shutdown_provider_sync_raises_container_shutdown_error_on_failure(self) -> None:
        logger = Mock()
        with self.assertRaises(di.ContainerShutdownError):
            di._shutdown_provider(  # pylint: disable=protected-access
                "failing-provider",
                _ProviderWithClose(raises=RuntimeError("close failed")),
                logger,
            )

    def test_shutdown_provider_sync_succeeds_without_failures(self) -> None:
        logger = Mock()
        di._shutdown_provider(  # pylint: disable=protected-access
            "ok-provider",
            _ProviderWithClose(awaitable=_AwaitableNoop()),
            logger,
        )
        logger.error.assert_not_called()

    def test_shutdown_injector_sync_raises_when_running_loop(self) -> None:
        logger = Mock()
        injector = SimpleNamespace(logging_gateway=logger)
        with patch("mugen.core.di.asyncio.get_running_loop", return_value=object()):
            with self.assertRaises(RuntimeError):
                di._shutdown_injector(injector)  # pylint: disable=protected-access
        logger.error.assert_not_called()

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
        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "none",
            None,
            logger,
        )
        self.assertEqual(failures, ())
        logger.error.assert_not_called()

    async def test_shutdown_provider_async_error_paths(self) -> None:
        logger = Mock()

        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "bad-close",
            _ProviderWithClose(raises=RuntimeError("close failed")),
            logger,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].provider_name, "bad-close")
        self.assertEqual(failures[0].hook_name, "close")
        self.assertIn("close failed", failures[0].reason)

        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "bad-aclose",
            _ProviderWithAClose(raises=RuntimeError("aclose failed")),
            logger,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].provider_name, "bad-aclose")
        self.assertEqual(failures[0].hook_name, "aclose")
        self.assertIn("aclose failed", failures[0].reason)

        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "await-fail",
            _ProviderWithClose(awaitable=_AwaitableBoom()),
            logger,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].provider_name, "await-fail")
        self.assertEqual(failures[0].hook_name, "close")
        self.assertIn("await failed", failures[0].reason)

        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "await-fail-aclose",
            _ProviderWithAClose(awaitable=_AwaitableBoom()),
            logger,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].provider_name, "await-fail-aclose")
        self.assertEqual(failures[0].hook_name, "aclose")
        self.assertIn("await failed", failures[0].reason)

    async def test_shutdown_provider_async_handles_non_awaitable_close_result(self) -> None:
        logger = Mock()
        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "non-awaitable",
            _ProviderWithClose(awaitable=None),
            logger,
        )
        self.assertEqual(failures, ())
        logger.error.assert_not_called()

    async def test_shutdown_provider_closes_awaitable_success(self) -> None:
        logger = Mock()
        closed = {"value": False}

        async def _close():
            closed["value"] = True

        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "async-close",
            _ProviderWithClose(awaitable=_close()),
            logger,
        )
        self.assertEqual(failures, ())
        self.assertTrue(closed["value"])

    async def test_shutdown_provider_async_times_out_when_hook_exceeds_limit(self) -> None:
        logger = Mock()

        async def _slow_close():
            await asyncio.sleep(0.05)

        failures = await di._shutdown_provider_async(  # pylint: disable=protected-access
            "slow-provider",
            _ProviderWithClose(awaitable=_slow_close()),
            logger,
            timeout_seconds=0.001,
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].provider_name, "slow-provider")
        self.assertEqual(failures[0].hook_name, "close")
        self.assertIn("timed out after", failures[0].reason)

    async def test_container_shutdown_error_formats_empty_failure_set(self) -> None:
        error = di.ContainerShutdownError(())
        self.assertEqual(str(error), "Container shutdown failed.")

    async def test_shutdown_injector_async_handles_duplicates_and_ext_services(self) -> None:
        logger = Mock()
        shared_provider = object()
        unique_service = object()
        injector = SimpleNamespace(
            config=SimpleNamespace(
                dict={
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "provider_readiness_timeout_seconds": 15.0,
                            "provider_shutdown_timeout_seconds": 0.5,
                            "shutdown_timeout_seconds": 5.0,
                            "phase_b": {"startup_timeout_seconds": 30.0},
                        }
                    }
                }
            ),
            logging_gateway=logger,
            completion_gateway=shared_provider,
            keyval_storage_gateway=shared_provider,
            ext_services={
                "shared": shared_provider,
                "unique": unique_service,
            },
        )

        with patch(
            "mugen.core.di._shutdown_provider_async",
            new=AsyncMock(return_value=()),
        ) as shutdown_mock:
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
        with patch(
            "mugen.core.di._shutdown_provider_async",
            new=AsyncMock(return_value=()),
        ) as shutdown_mock:
            await di._shutdown_injector_async(_ExtServicesBoom())  # pylint: disable=protected-access
        self.assertTrue(
            all(
                not str(call.args[0]).startswith("ext_service:")
                for call in shutdown_mock.call_args_list
            )
        )

    async def test_shutdown_injector_async_uses_configured_provider_timeout(self) -> None:
        logger = Mock()
        injector = SimpleNamespace(
            config=SimpleNamespace(
                dict={
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "provider_readiness_timeout_seconds": 15.0,
                            "provider_shutdown_timeout_seconds": 0.5,
                            "shutdown_timeout_seconds": 5.0,
                            "phase_b": {"startup_timeout_seconds": 30.0},
                        }
                    }
                }
            ),
            logging_gateway=logger,
            completion_gateway=object(),
        )
        spec = di._PROVIDER_SPECS["completion_gateway"]  # pylint: disable=protected-access
        with (
            patch("mugen.core.di._provider_specs_for_shutdown", return_value=[spec]),
            patch(
                "mugen.core.di._shutdown_provider_async",
                new=AsyncMock(return_value=()),
            ) as shutdown_mock,
        ):
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        self.assertEqual(
            shutdown_mock.await_args.kwargs["timeout_seconds"],
            0.5,
        )

    async def test_shutdown_injector_async_preserves_duplicate_reference_when_failure_occurs(
        self,
    ) -> None:
        logger = Mock()
        shared_provider = object()
        injector = SimpleNamespace(
            config=SimpleNamespace(dict=_runtime_config_dict()),
            logging_gateway=logger,
            completion_gateway=shared_provider,
            keyval_storage_gateway=shared_provider,
        )
        completion_spec = di._PROVIDER_SPECS["completion_gateway"]  # pylint: disable=protected-access
        keyval_spec = di._PROVIDER_SPECS["keyval_storage_gateway"]  # pylint: disable=protected-access
        failure = di.ProviderShutdownFailure(
            provider_name="completion_gateway",
            hook_name="close",
            reason="RuntimeError: close failed",
        )

        with (
            patch(
                "mugen.core.di._provider_specs_for_shutdown",
                return_value=[completion_spec, keyval_spec],
            ),
            patch(
                "mugen.core.di._shutdown_provider_async",
                new=AsyncMock(return_value=(failure,)),
            ) as shutdown_mock,
            self.assertRaises(di.ContainerShutdownError),
        ):
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        shutdown_mock.assert_awaited_once()
        self.assertIs(injector.completion_gateway, shared_provider)
        self.assertIs(injector.keyval_storage_gateway, shared_provider)

    async def test_shutdown_injector_async_collects_ext_service_failures(self) -> None:
        logger = Mock()
        ext_service = object()
        injector = SimpleNamespace(
            config=SimpleNamespace(dict=_runtime_config_dict()),
            logging_gateway=logger,
            ext_services={"bad": ext_service},
        )
        failure = di.ProviderShutdownFailure(
            provider_name="ext_service:bad",
            hook_name="close",
            reason="RuntimeError: close failed",
        )

        with (
            patch("mugen.core.di._provider_specs_for_shutdown", return_value=[]),
            patch(
                "mugen.core.di._shutdown_provider_async",
                new=AsyncMock(return_value=(failure,)),
            ),
            self.assertRaises(di.ContainerShutdownError) as ctx,
        ):
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        self.assertIn("ext_service:bad", str(ctx.exception))

    async def test_shutdown_injector_async_collects_relational_runtime_failures(
        self,
    ) -> None:
        logger = Mock()
        relational_runtime = object()
        injector = SimpleNamespace(
            config=SimpleNamespace(dict=_runtime_config_dict()),
            logging_gateway=logger,
            ext_services={},
            relational_runtime=relational_runtime,
        )
        failure = di.ProviderShutdownFailure(
            provider_name="relational_runtime",
            hook_name="close",
            reason="RuntimeError: close failed",
        )

        with (
            patch("mugen.core.di._provider_specs_for_shutdown", return_value=[]),
            patch(
                "mugen.core.di._shutdown_provider_async",
                new=AsyncMock(return_value=(failure,)),
            ),
            self.assertRaises(di.ContainerShutdownError) as ctx,
        ):
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        self.assertIn("relational_runtime", str(ctx.exception))
        self.assertIs(injector.relational_runtime, relational_runtime)

    async def test_shutdown_injector_async_clears_relational_runtime_on_success(
        self,
    ) -> None:
        logger = Mock()
        relational_runtime = object()
        injector = SimpleNamespace(
            config=SimpleNamespace(dict=_runtime_config_dict()),
            logging_gateway=logger,
            ext_services={},
            relational_runtime=relational_runtime,
        )

        with (
            patch("mugen.core.di._provider_specs_for_shutdown", return_value=[]),
            patch(
                "mugen.core.di._shutdown_provider_async",
                new=AsyncMock(return_value=()),
            ),
        ):
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        self.assertIsNone(injector.relational_runtime)

    async def test_shutdown_injector_async_rejects_invalid_timeout_config(
        self,
    ) -> None:
        logger = Mock()
        injector = SimpleNamespace(
            config=SimpleNamespace(
                dict={
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "provider_readiness_timeout_seconds": 15.0,
                            "provider_shutdown_timeout_seconds": "invalid",
                            "shutdown_timeout_seconds": 5.0,
                            "phase_b": {"startup_timeout_seconds": 30.0},
                        }
                    }
                }
            ),
            logging_gateway=logger,
            completion_gateway=object(),
        )
        spec = di._PROVIDER_SPECS["completion_gateway"]  # pylint: disable=protected-access
        with (
            patch("mugen.core.di._provider_specs_for_shutdown", return_value=[spec]),
            patch(
                "mugen.core.di._shutdown_provider_async",
                new=AsyncMock(return_value=()),
            ) as shutdown_mock,
        ):
            with self.assertRaises(RuntimeError):
                await di._shutdown_injector_async(injector)  # pylint: disable=protected-access
        shutdown_mock.assert_not_awaited()

    async def test_shutdown_injector_async_raises_when_global_timeout_expires(self) -> None:
        logger = Mock()
        injector = SimpleNamespace(
            config=SimpleNamespace(
                dict={
                    "mugen": {
                        "runtime": {
                            "profile": "platform_full",
                            "provider_readiness_timeout_seconds": 15.0,
                            "provider_shutdown_timeout_seconds": 0.5,
                            "shutdown_timeout_seconds": 1.0,
                            "phase_b": {"startup_timeout_seconds": 30.0},
                        }
                    }
                }
            ),
            logging_gateway=logger,
        )

        def _raise_timeout(awaitable, timeout):  # noqa: ARG001
            awaitable.close()
            raise asyncio.TimeoutError

        with (
            patch("mugen.core.di.asyncio.wait_for", side_effect=_raise_timeout),
            self.assertRaises(di.ContainerShutdownError),
        ):
            await di._shutdown_injector_async(injector)  # pylint: disable=protected-access

        self.assertIn(
            "injector shutdown timed out",
            logger.error.call_args.args[0],
        )

    async def test_shutdown_container_async_delegates_to_proxy(self) -> None:
        with patch.object(
            di._ContainerProxy,  # pylint: disable=protected-access
            "shutdown_async",
            new=AsyncMock(),
        ) as shutdown_mock:
            await di.shutdown_container_async()
        shutdown_mock.assert_awaited_once_with()

    async def test_container_proxy_shutdown_async_preserves_injector_on_failure(self) -> None:
        proxy = di._ContainerProxy()  # pylint: disable=protected-access
        marker = object()
        proxy._injector = marker  # pylint: disable=protected-access
        proxy._readiness_checked = True  # pylint: disable=protected-access
        proxy._last_readiness_report = object()  # pylint: disable=protected-access

        failure = di.ProviderShutdownFailure(
            provider_name="completion_gateway",
            hook_name="close",
            reason="RuntimeError: boom",
        )
        with (
            patch(
                "mugen.core.di._shutdown_injector_async",
                new=AsyncMock(
                    side_effect=di.ContainerShutdownError((failure,))
                ),
            ),
            self.assertRaises(di.ContainerShutdownError),
        ):
            await proxy.shutdown_async()

        self.assertIs(proxy._injector, marker)  # pylint: disable=protected-access
        self.assertTrue(proxy._readiness_checked)  # pylint: disable=protected-access
        self.assertIsNotNone(proxy._last_readiness_report)  # pylint: disable=protected-access
