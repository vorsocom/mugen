"""Unit tests for signal multi-profile client management."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from mugen.core.client import signal as signal_mod
from mugen.core.utility.platform_runtime_profile import (
    build_config_namespace,
    runtime_profile_scope,
)


def _signal_config(*profiles: dict) -> SimpleNamespace:
    return build_config_namespace({"signal": {"profiles": list(profiles)}})


class _FakeSignalProfileClient:
    instances: list["_FakeSignalProfileClient"] = []

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        signal_cfg = config.signal
        self.runtime_profile_key = signal_cfg.runtime_profile_key
        self._events = []
        for item in list(getattr(signal_cfg, "events", [])):
            raw = getattr(item, "dict", None)
            if isinstance(raw, dict):
                self._events.append(dict(raw))
                continue
            self._events.append(item)
        self._receive_error = getattr(signal_cfg, "receive_error", None)
        self._verify_result = bool(getattr(signal_cfg, "verify_result", True))
        self._stop = asyncio.Event()
        self.init = AsyncMock()
        self.verify_startup = AsyncMock(return_value=self._verify_result)
        self.close = AsyncMock(side_effect=self._close)
        self.send_text_message = AsyncMock(
            return_value={"method": "send_text_message", "key": self.runtime_profile_key}
        )
        self.send_media_message = AsyncMock(
            return_value={"method": "send_media_message", "key": self.runtime_profile_key}
        )
        self.send_reaction = AsyncMock(
            return_value={"method": "send_reaction", "key": self.runtime_profile_key}
        )
        self.send_receipt = AsyncMock(
            return_value={"method": "send_receipt", "key": self.runtime_profile_key}
        )
        self.emit_processing_signal = AsyncMock(
            return_value={"method": "emit_processing_signal", "key": self.runtime_profile_key}
        )
        self.download_attachment = AsyncMock(
            return_value={"method": "download_attachment", "key": self.runtime_profile_key}
        )
        _FakeSignalProfileClient.instances.append(self)

    async def _close(self) -> None:
        self._stop.set()

    async def receive_events(self):
        if self._receive_error is not None:
            raise self._receive_error
        for item in self._events:
            yield item
        await self._stop.wait()


class TestMuGenMultiProfileSignalClient(unittest.IsolatedAsyncioTestCase):
    """Covers Signal-specific reader task and delegation behavior."""

    def setUp(self) -> None:
        _FakeSignalProfileClient.instances.clear()

    async def test_init_reader_tasks_receive_events_and_delegate_methods(self) -> None:
        config = _signal_config(
            {"key": "default", "events": ["skip-me", {"id": 1}]},
            {"key": "secondary", "events": []},
        )
        with patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient):
            client = signal_mod.MultiProfileSignalClient(config=config)

            async with client._lock:  # pylint: disable=protected-access
                await client._stop_reader_tasks_locked()  # pylint: disable=protected-access

            await client.init()
            async with client._lock:  # pylint: disable=protected-access
                await client._start_reader_tasks_locked(client._clients)  # pylint: disable=protected-access

            event = await anext(client.receive_events())
            self.assertEqual(event["id"], 1)
            self.assertEqual(event["runtime_profile_key"], "default")

            with runtime_profile_scope("secondary"):
                self.assertEqual(
                    (await client.send_text_message(recipient="+1", text="hello"))["key"],
                    "secondary",
                )
                self.assertEqual(
                    (
                        await client.send_media_message(
                            recipient="+1",
                            message="hello",
                            base64_attachments=["abc"],
                        )
                    )["method"],
                    "send_media_message",
                )
                self.assertEqual(
                    (
                        await client.send_reaction(
                            recipient="+1",
                            reaction="👍",
                            target_author="+2",
                            timestamp=1,
                            remove=True,
                        )
                    )["method"],
                    "send_reaction",
                )
                self.assertEqual(
                    (
                        await client.send_receipt(
                            recipient="+1",
                            receipt_type="read",
                            timestamp=2,
                        )
                    )["method"],
                    "send_receipt",
                )
                self.assertEqual(
                    (
                        await client.emit_processing_signal(
                            "+1",
                            state="start",
                            message_id="m1",
                        )
                    )["method"],
                    "emit_processing_signal",
                )
                self.assertEqual(
                    (await client.download_attachment("att-1"))["method"],
                    "download_attachment",
                )

            await client.close()
            await client.close()
            self.assertEqual(client._reader_tasks, {})  # pylint: disable=protected-access

    async def test_receive_events_propagates_reader_failure(self) -> None:
        config = _signal_config(
            {"key": "default", "receive_error": RuntimeError("reader boom")}
        )
        with patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient):
            client = signal_mod.MultiProfileSignalClient(config=config)

            with self.assertRaisesRegex(
                RuntimeError,
                "runtime_profile_key='default'",
            ):
                await anext(client.receive_events())

            await client.close()

    async def test_reader_loop_handles_clean_exit_and_receive_events_skips_non_dict(
        self,
    ) -> None:
        config = _signal_config({"key": "default", "events": []})
        with patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient):
            client = signal_mod.MultiProfileSignalClient(config=config)
            managed_client = next(iter(client._clients.values()))  # pylint: disable=protected-access

            async def _receive_events():
                if False:
                    yield {}

            managed_client.receive_events = _receive_events
            await client._reader_loop("default", managed_client)  # pylint: disable=protected-access
            self.assertTrue(client._event_queue.empty())  # pylint: disable=protected-access

            client.init = AsyncMock()
            client._event_queue.put_nowait("skip-me")  # pylint: disable=protected-access
            client._event_queue.put_nowait({"id": 2})  # pylint: disable=protected-access
            event = await asyncio.wait_for(anext(client.receive_events()), timeout=1)
            self.assertEqual(event, {"id": 2})

    async def test_reload_profiles_success_and_failure_paths(self) -> None:
        config = _signal_config({"key": "default", "events": []})
        next_config = _signal_config(
            {"key": "default", "events": [], "api": {"base_url": "changed"}},
            {"key": "secondary", "events": []},
        )
        bad_config = _signal_config(
            {"key": "default", "events": [], "verify_result": False}
        )

        with patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient):
            client = signal_mod.MultiProfileSignalClient(config=config)
            await client.init()
            current_clients = tuple(client._clients.values())  # pylint: disable=protected-access

            diff = await client.reload_profiles(next_config)
            self.assertEqual(diff["added"], ["secondary"])
            self.assertEqual(diff["removed"], [])
            self.assertEqual(diff["updated"], ["default"])
            self.assertEqual(diff["unchanged"], [])
            for current_client in current_clients:
                current_client.close.assert_awaited()

            with self.assertRaisesRegex(RuntimeError, "startup probe failed"):
                await client.reload_profiles(bad_config)

            await client.close()
