"""Provides unit tests for mugen.run_signal_client."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from quart import Quart

import mugen as mugen_module
from mugen import run_signal_client

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000205")


class _IPCService:
    def __init__(self, *, errors: list[str] | None = None) -> None:
        self._errors = list(errors or [])
        self.requests: list[object] = []

    async def handle_ipc_request(self, request):
        self.requests.append(request)
        return SimpleNamespace(errors=list(self._errors))


class TestMuGenInitRunSignalClient(unittest.IsolatedAsyncioTestCase):
    """Unit tests for mugen.run_signal_client."""

    async def test_signal_helper_functions_and_stage_entry_extractor(self) -> None:
        self.assertIsNone(mugen_module._nonempty_text(1))  # pylint: disable=protected-access
        self.assertEqual(
            mugen_module._nonempty_text(" hello "),  # pylint: disable=protected-access
            "hello",
        )
        self.assertTrue(
            mugen_module._json_hash({"a": 1})  # pylint: disable=protected-access
        )
        self.assertIsNone(
            mugen_module.signal_envelope({"params": []})
        )
        envelope = {
            "sourceNumber": "+15550001",
            "timestamp": 123,
            "dataMessage": {"reaction": {"emoji": "👍"}},
        }
        self.assertEqual(
            mugen_module.signal_envelope({"params": {"envelope": envelope}}),
            envelope,
        )
        self.assertEqual(
            mugen_module.signal_sender({"sourceUuid": "uuid-1"}),
            "uuid-1",
        )
        self.assertIsNone(
            mugen_module.signal_event_id({"timestamp": True})
        )
        self.assertIsNone(
            mugen_module.signal_event_id({"timestamp": "bad"})
        )
        self.assertEqual(
            mugen_module.signal_event_id({"timestamp": 5}),
            "5",
        )
        self.assertEqual(
            mugen_module.signal_event_id(
                {"timestamp": 6, "source": "+15550002"}
            ),
            "+15550002:6",
        )
        self.assertEqual(
            mugen_module.signal_event_type({"receiptMessage": {}}),
            "receipt",
        )
        self.assertEqual(
            mugen_module.signal_event_type({"typingMessage": {}}),
            "typing",
        )
        self.assertEqual(
            mugen_module.signal_event_type({"other": True}),
            "event",
        )
        self.assertEqual(
            mugen_module.resolve_signal_account_number(
                payload={"account_number": " +15550000009 "},
                config=None,
            ),
            "+15550000009",
        )
        self.assertEqual(
            mugen_module.resolve_signal_account_number(
                payload={"provider_context": {"account_number": " +15550000010 "}},
                config=None,
            ),
            "+15550000010",
        )
        self.assertIsNone(
            mugen_module.resolve_signal_account_number(
                payload={},
                config=None,
            )
        )
        self.assertEqual(
            mugen_module.resolve_signal_account_number(
                payload=None,
                config=SimpleNamespace(
                    signal=SimpleNamespace(
                        account=SimpleNamespace(number="+15550000011")
                    )
                ),
            ),
            "+15550000011",
        )
        self.assertEqual(
            mugen_module._extract_signal_stage_entries(  # pylint: disable=protected-access
                config=SimpleNamespace(
                    signal=SimpleNamespace(
                        account=SimpleNamespace(number="+15550000001")
                    )
                ),
                payload={"params": {}},
            ),
            [],
        )

        entries = mugen_module._extract_signal_stage_entries(  # pylint: disable=protected-access
            config=SimpleNamespace(
                signal=SimpleNamespace(
                    account=SimpleNamespace(number="+15550000001"),
                )
            ),
            payload={
                "client_profile_id": str(_CLIENT_PROFILE_ID),
                "params": {"envelope": envelope},
            },
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].ipc_command, "signal_ingress_event")
        self.assertEqual(entries[0].event.event_type, "reaction")
        self.assertEqual(entries[0].event.event_id, "+15550001:123")
        self.assertEqual(entries[0].event.identifier_value, "+15550000001")
        self.assertEqual(entries[0].event.sender, "+15550001")
        self.assertEqual(entries[0].event.client_profile_id, _CLIENT_PROFILE_ID)

        provider_context_entries = mugen_module._extract_signal_stage_entries(  # pylint: disable=protected-access
            config=SimpleNamespace(
                signal=SimpleNamespace(
                    account=SimpleNamespace(number="+15550000001"),
                )
            ),
            payload={
                "provider_context": {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "account_number": "+15550000011",
                },
                "params": {"envelope": envelope},
            },
        )
        self.assertEqual(len(provider_context_entries), 1)
        self.assertEqual(
            provider_context_entries[0].event.identifier_value,
            "+15550000011",
        )
        self.assertEqual(
            mugen_module._extract_signal_stage_entries(  # pylint: disable=protected-access
                config=SimpleNamespace(
                    signal=SimpleNamespace(
                        account=SimpleNamespace(number="+15550000001")
                    )
                ),
                payload={"params": {"envelope": envelope}},
            ),
            [],
        )

    async def test_normal_run_dispatches_ipc_events(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                yield {"method": "receive", "params": {"envelope": {"timestamp": 1}}}
                await asyncio.Event().wait()

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            task = asyncio.create_task(
                run_signal_client(
                    logger_provider=lambda: app.logger,
                    signal_provider=DummySignalClient,
                    ipc_provider=lambda: ipc,
                )
            )
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.assertEqual(logger.output[0], "DEBUG:test_app:Signal client started.")
        self.assertEqual(logger.output[1], "DEBUG:test_app:Signal client shutting down.")
        self.assertEqual(len(ipc.requests), 1)
        self.assertEqual(ipc.requests[0].platform, "signal")
        self.assertEqual(ipc.requests[0].command, "signal_restapi_event")

    async def test_ipc_errors_are_logged(self) -> None:
        logger = Mock()
        ipc = _IPCService(errors=["oops"])

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                yield {"method": "receive", "params": {"envelope": {"timestamp": 1}}}
                await asyncio.Event().wait()

        task = asyncio.create_task(
            run_signal_client(
                logger_provider=lambda: logger,
                signal_provider=DummySignalClient,
                ipc_provider=lambda: ipc,
            )
        )
        for _ in range(10):
            if ipc.requests:
                break
            await asyncio.sleep(0)
        for _ in range(20):
            if any(
                "Signal receive event processed with IPC errors" in str(call.args[0])
                for call in logger.warning.call_args_list
            ):
                break
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(
            any(
                "Signal receive event processed with IPC errors" in str(call.args[0])
                for call in logger.warning.call_args_list
            )
        )

    async def test_close_error_is_logged(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                raise RuntimeError("boom")

            async def receive_events(self):
                await asyncio.Event().wait()
                if False:
                    yield {}

        with self.assertLogs(logger="test_app", level="DEBUG") as logger:
            task = asyncio.create_task(
                run_signal_client(
                    logger_provider=lambda: app.logger,
                    signal_provider=DummySignalClient,
                    ipc_provider=lambda: ipc,
                )
            )
            await asyncio.sleep(0)
            task.cancel()
            results = await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(any("Signal client shutdown failed" in line for line in logger.output))
        self.assertTrue(
            any(
                isinstance(result, RuntimeError)
                and "shutdown failed during cancellation" in str(result)
                for result in results
            )
        )

    async def test_close_error_is_raised_when_runtime_has_no_primary_error(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                raise RuntimeError("close failed")

            async def receive_events(self):
                if False:
                    yield {}
                return

        with (
            unittest.mock.patch(
                "mugen.asyncio.sleep",
                new=AsyncMock(side_effect=SystemExit("stop")),
            ),
            self.assertRaisesRegex(RuntimeError, "close failed"),
        ):
            await run_signal_client(
                logger_provider=lambda: app.logger,
                signal_provider=DummySignalClient,
                ipc_provider=lambda: ipc,
            )

    async def test_started_callback_is_invoked(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()
        started = Mock()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                await asyncio.Event().wait()
                if False:
                    yield {}

        task = asyncio.create_task(
            run_signal_client(
                logger_provider=lambda: app.logger,
                signal_provider=DummySignalClient,
                ipc_provider=lambda: ipc,
                started_callback=started,
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        started.assert_called_once_with()

    async def test_probe_failure_does_not_invoke_started_callback(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()
        started = Mock()
        closed = AsyncMock()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return False

            async def close(self) -> None:
                await closed()

            async def receive_events(self):
                if False:
                    yield {}
                return

        with self.assertRaises(RuntimeError):
            await run_signal_client(
                logger_provider=lambda: app.logger,
                signal_provider=DummySignalClient,
                ipc_provider=lambda: ipc,
                started_callback=started,
            )

        started.assert_not_called()
        closed.assert_awaited_once()

    async def test_receive_loop_degrades_and_recovers_with_callbacks(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()
        degraded = Mock()
        healthy = Mock()
        closed = AsyncMock()
        degraded_event = asyncio.Event()
        recovered_event = asyncio.Event()

        class DummySignalClient:
            def __init__(self) -> None:
                self._receive_calls = 0

            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                await closed()

            async def receive_events(self):
                self._receive_calls += 1
                if self._receive_calls == 1:
                    raise RuntimeError("down")
                yield {"method": "receive", "params": {"envelope": {"timestamp": 1}}}
                await asyncio.Event().wait()

        with unittest.mock.patch(
            "mugen.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):

            def _on_degraded(reason: str) -> None:
                degraded(reason)
                degraded_event.set()

            def _on_healthy() -> None:
                healthy()
                if healthy.call_count >= 2:
                    recovered_event.set()

            task = asyncio.create_task(
                run_signal_client(
                    logger_provider=lambda: app.logger,
                    signal_provider=DummySignalClient,
                    ipc_provider=lambda: ipc,
                    degraded_callback=_on_degraded,
                    healthy_callback=_on_healthy,
                )
            )
            await asyncio.wait_for(degraded_event.wait(), timeout=1.0)
            await asyncio.wait_for(recovered_event.wait(), timeout=1.0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        degraded.assert_called_once_with("RuntimeError: down")
        self.assertEqual(healthy.call_count, 2)
        closed.assert_awaited_once()

    async def test_reconnect_controls_normalize_invalid_and_bounded_values(self) -> None:
        cfg_invalid = SimpleNamespace(
            signal=SimpleNamespace(
                receive=SimpleNamespace(
                    reconnect_base_seconds="bad",
                    reconnect_max_seconds=-1,
                    reconnect_jitter_seconds="bad",
                )
            )
        )
        self.assertEqual(
            mugen_module._resolve_signal_reconnect_controls(cfg_invalid),  # pylint: disable=protected-access
            (1.0, 30.0, 0.25),
        )

        cfg_zero = SimpleNamespace(
            signal=SimpleNamespace(
                receive=SimpleNamespace(
                    reconnect_base_seconds=0,
                    reconnect_max_seconds=0,
                    reconnect_jitter_seconds=0.1,
                )
            )
        )
        self.assertEqual(
            mugen_module._resolve_signal_reconnect_controls(cfg_zero),  # pylint: disable=protected-access
            (1.0, 30.0, 0.1),
        )

        cfg_max_lt_base = SimpleNamespace(
            signal=SimpleNamespace(
                receive=SimpleNamespace(
                    reconnect_base_seconds=5,
                    reconnect_max_seconds=1,
                    reconnect_jitter_seconds=0,
                )
            )
        )
        self.assertEqual(
            mugen_module._resolve_signal_reconnect_controls(cfg_max_lt_base),  # pylint: disable=protected-access
            (5.0, 5.0, 0.0),
        )

    async def test_receive_loop_recovers_without_callbacks(self) -> None:
        logger = Mock()
        ipc = _IPCService()
        event_forwarded = asyncio.Event()

        class DummySignalClient:
            def __init__(self) -> None:
                self._receive_calls = 0

            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                self._receive_calls += 1
                if self._receive_calls == 1:
                    raise RuntimeError("down")
                event_forwarded.set()
                yield {"method": "receive", "params": {"envelope": {"timestamp": 1}}}
                await asyncio.Event().wait()

        with unittest.mock.patch(
            "mugen.asyncio.sleep",
            new=AsyncMock(return_value=None),
        ):
            task = asyncio.create_task(
                run_signal_client(
                    logger_provider=lambda: logger,
                    signal_provider=DummySignalClient,
                    ipc_provider=lambda: ipc,
                )
            )
            await asyncio.wait_for(event_forwarded.wait(), timeout=1.0)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.assertGreaterEqual(len(ipc.requests), 1)
        self.assertTrue(
            any(
                "Signal receive loop failed" in str(call.args[0])
                for call in logger.warning.call_args_list
            )
        )

    async def test_startup_exception_calls_degraded_callback(self) -> None:
        app = Quart("test_app")
        ipc = _IPCService()
        degraded = Mock()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                raise RuntimeError("startup exploded")

            async def close(self) -> None:
                return None

            async def receive_events(self):
                if False:
                    yield {}

        with self.assertRaisesRegex(RuntimeError, "startup exploded"):
            await run_signal_client(
                logger_provider=lambda: app.logger,
                signal_provider=DummySignalClient,
                ipc_provider=lambda: ipc,
                degraded_callback=degraded,
            )

        degraded.assert_called_once_with("RuntimeError: startup exploded")

    async def test_ingress_mode_stages_events_when_ipc_provider_is_absent(self) -> None:
        ingress_service = SimpleNamespace(stage=AsyncMock())
        event_forwarded = asyncio.Event()

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                yield {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "params": {
                        "envelope": {
                            "sourceNumber": "+15550001",
                            "timestamp": 123,
                            "dataMessage": {"message": "hello"},
                        }
                    }
                }
                event_forwarded.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(
            run_signal_client(
                config_provider=lambda: SimpleNamespace(
                    signal=SimpleNamespace(
                        account="+15550000001",
                        receive=SimpleNamespace(),
                    )
                ),
                logger_provider=lambda: Mock(),
                signal_provider=DummySignalClient,
                ingress_provider=lambda: ingress_service,
            )
        )
        await asyncio.wait_for(event_forwarded.wait(), timeout=1.0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        ingress_service.stage.assert_awaited_once()
        staged_entries = ingress_service.stage.await_args.args[0]
        self.assertEqual(len(staged_entries), 1)
        self.assertEqual(staged_entries[0].ipc_command, "signal_ingress_event")

    async def test_ingress_mode_requires_ingress_service(self) -> None:
        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                if False:
                    yield {}

        with self.assertRaisesRegex(RuntimeError, "Signal ingress service unavailable"):
            await run_signal_client(
                config_provider=lambda: SimpleNamespace(
                    signal=SimpleNamespace(
                        account="+15550000001",
                        receive=SimpleNamespace(),
                    )
                ),
                logger_provider=lambda: Mock(),
                signal_provider=DummySignalClient,
                ingress_provider=lambda: None,
            )

    async def test_ipc_mode_falls_back_to_empty_config_when_config_provider_raises(
        self,
    ) -> None:
        ipc = _IPCService()
        handled_event = asyncio.Event()

        async def _handle_request(request):
            handled_event.set()
            return SimpleNamespace(errors=[])

        ipc.handle_ipc_request = AsyncMock(side_effect=_handle_request)

        class DummySignalClient:
            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                yield {
                    "params": {
                        "envelope": {
                            "sourceNumber": "+15550001",
                            "timestamp": 123,
                            "dataMessage": {"message": "hello"},
                        }
                    }
                }
                await asyncio.Event().wait()

        task = asyncio.create_task(
            run_signal_client(
                config_provider=Mock(side_effect=RuntimeError("config unavailable")),
                logger_provider=lambda: Mock(),
                signal_provider=DummySignalClient,
                ipc_provider=lambda: ipc,
            )
        )

        await asyncio.wait_for(handled_event.wait(), timeout=1.0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        ipc.handle_ipc_request.assert_awaited_once()
