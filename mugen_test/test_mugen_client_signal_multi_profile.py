"""Unit tests for ACP-backed signal multi-profile client management."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid

from mugen.core.client import runtime_profile_manager as rpm_mod
from mugen.core.client import signal as signal_mod
from mugen.core.plugin.acp.service.messaging_client_profile import (
    RuntimeMessagingClientProfileSpec,
)
from mugen.core.utility.client_profile_runtime import client_profile_scope
from mugen.core.utility.platform_runtime_profile import build_config_namespace

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000111")
_DEFAULT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_SECONDARY_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _root_config() -> SimpleNamespace:
    return build_config_namespace({})


def _signal_spec(
    *,
    client_profile_id: uuid.UUID,
    profile_key: str,
    account_number: str,
    events: list[object] | None = None,
    receive_error: BaseException | None = None,
    verify_result: bool = True,
    api_base_url: str = "https://signal.test",
) -> RuntimeMessagingClientProfileSpec:
    settings = {
        "client_profile_id": str(client_profile_id),
        "client_profile_key": profile_key,
        "account": {"number": account_number},
        "api": {"base_url": api_base_url, "bearer_token": "token"},
        "media": {"allowed_mimetypes": ["image/png"]},
        "events": list(events or []),
        "verify_result": verify_result,
    }
    if receive_error is not None:
        settings["receive_error"] = receive_error
    return RuntimeMessagingClientProfileSpec(
        client_profile_id=client_profile_id,
        tenant_id=_TENANT_ID,
        platform_key="signal",
        profile_key=profile_key,
        config=build_config_namespace({"signal": settings}),
        snapshot={
            "id": str(client_profile_id),
            "profile_key": profile_key,
            "account_number": account_number,
            "api_base_url": api_base_url,
            "verify_result": verify_result,
        },
    )


class _MessagingClientProfileServiceStub:
    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def list_active_runtime_specs(
        self,
        *,
        config,
        platform_key: str,
    ) -> tuple[RuntimeMessagingClientProfileSpec, ...]:
        _ = config
        if platform_key != "signal":
            return ()
        index = min(self.calls, max(len(self._responses) - 1, 0))
        self.calls += 1
        return self._responses[index] if self._responses else ()


class _FakeSignalProfileClient:
    instances: list["_FakeSignalProfileClient"] = []

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        self._config = config
        signal_cfg = config.signal
        self.client_profile_id = str(signal_cfg.client_profile_id)
        self.client_profile_key = str(signal_cfg.client_profile_key)
        self._account_number = str(signal_cfg.account.number)
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
            return_value={
                "method": "send_text_message",
                "client_profile_id": self.client_profile_id,
            }
        )
        self.send_media_message = AsyncMock(
            return_value={
                "method": "send_media_message",
                "client_profile_id": self.client_profile_id,
            }
        )
        self.send_reaction = AsyncMock(
            return_value={
                "method": "send_reaction",
                "client_profile_id": self.client_profile_id,
            }
        )
        self.send_receipt = AsyncMock(
            return_value={
                "method": "send_receipt",
                "client_profile_id": self.client_profile_id,
            }
        )
        self.emit_processing_signal = AsyncMock(
            return_value={
                "method": "emit_processing_signal",
                "client_profile_id": self.client_profile_id,
            }
        )
        self.download_attachment = AsyncMock(
            return_value={
                "method": "download_attachment",
                "client_profile_id": self.client_profile_id,
            }
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
        service = _MessagingClientProfileServiceStub(
            (
                _signal_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    account_number="+1001",
                    events=["skip-me", {"id": 1}],
                ),
                _signal_spec(
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                    account_number="+1002",
                    events=[],
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient),
        ):
            client = signal_mod.MultiProfileSignalClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()

            event = await asyncio.wait_for(anext(client.receive_events()), timeout=1)
            self.assertEqual(event["id"], 1)
            self.assertEqual(event["client_profile_id"], str(_DEFAULT_ID))
            self.assertEqual(event["account_number"], "+1001")
            self.assertEqual(event["client_profile_key"], "default")

            with client_profile_scope(_SECONDARY_ID):
                self.assertEqual(
                    (
                        await client.send_text_message(
                            recipient="+1",
                            text="hello",
                        )
                    )["client_profile_id"],
                    str(_SECONDARY_ID),
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
        service = _MessagingClientProfileServiceStub(
            (
                _signal_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    account_number="+1001",
                    receive_error=RuntimeError("reader boom"),
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient),
        ):
            client = signal_mod.MultiProfileSignalClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with self.assertRaisesRegex(
                RuntimeError,
                f"client_profile_id='{_DEFAULT_ID}'",
            ):
                await asyncio.wait_for(anext(client.receive_events()), timeout=1)

            await client.close()

    async def test_reload_profiles_success_and_failure_paths(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _signal_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    account_number="+1001",
                    events=[],
                ),
            ),
            (
                _signal_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    account_number="+1001",
                    events=[],
                    api_base_url="https://signal.changed",
                ),
                _signal_spec(
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                    account_number="+1002",
                    events=[],
                ),
            ),
            (
                _signal_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    account_number="+1001",
                    events=[],
                    verify_result=False,
                ),
            ),
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient),
        ):
            client = signal_mod.MultiProfileSignalClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            current_clients = tuple(client._clients.values())  # pylint: disable=protected-access

            diff = await client.reload_profiles(_root_config())
            self.assertEqual(diff["added"], [str(_SECONDARY_ID)])
            self.assertEqual(diff["removed"], [])
            self.assertEqual(diff["updated"], [str(_DEFAULT_ID)])
            self.assertEqual(diff["unchanged"], [])
            for current_client in current_clients:
                current_client.close.assert_awaited()

            with self.assertRaisesRegex(RuntimeError, "startup probe failed"):
                await client.reload_profiles(_root_config())

            await client.close()

    async def test_reader_loop_optional_metadata_and_receive_events_skip_non_dict(
        self,
    ) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _signal_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    account_number="+1001",
                    events=[{"id": 1}],
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(signal_mod, "DefaultSignalClient", _FakeSignalProfileClient),
        ):
            client = signal_mod.MultiProfileSignalClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            managed = client._clients[str(_DEFAULT_ID)]  # pylint: disable=protected-access
            managed._account_number = " "
            managed._config.signal.client_profile_key = "   "
            managed._stop.set()

            await client._reader_loop(  # pylint: disable=protected-access
                str(_DEFAULT_ID),
                managed,
            )
            payload = await asyncio.wait_for(
                client._event_queue.get(),  # pylint: disable=protected-access
                timeout=1,
            )
            self.assertNotIn("account_number", payload)
            self.assertNotIn("client_profile_key", payload)

            client._event_queue.put_nowait("skip")  # pylint: disable=protected-access
            client._event_queue.put_nowait({"id": 2})  # pylint: disable=protected-access
            self.assertEqual(
                await asyncio.wait_for(anext(client.receive_events()), timeout=1),
                {"id": 2},
            )
            await client.close()
