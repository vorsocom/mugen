"""Unit tests for ACP-backed matrix multi-profile client management."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, PropertyMock, patch
import uuid

from mugen.core.client import matrix as matrix_mod
from mugen.core.plugin.acp.service.messaging_client_profile import (
    RuntimeMessagingClientProfileSpec,
)
from mugen.core.utility.platform_runtime_profile import build_config_namespace

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000111")
_DEFAULT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_SECONDARY_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_TERTIARY_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _root_config() -> SimpleNamespace:
    return build_config_namespace(
        {
            "basedir": "/tmp/mugen",
            "matrix": {},
        }
    )


def _matrix_spec(
    *,
    client_profile_id: uuid.UUID,
    profile_key: str,
    user: str,
    device: str | None = None,
    room_id: str | None = None,
    displayname: str = "",
    fail_before_sync: bool = False,
    return_before_sync: bool = False,
    health_fail: bool = False,
    close_error: str | None = None,
) -> RuntimeMessagingClientProfileSpec:
    settings = {
        "client": {
            "user": user,
            "device": device or f"device-{profile_key}",
        },
        "room_id": room_id or f"!{profile_key}:test",
        "profile_displayname": displayname,
        "client_profile_id": str(client_profile_id),
        "client_profile_key": profile_key,
    }
    if fail_before_sync:
        settings["fail_before_sync"] = True
    if return_before_sync:
        settings["return_before_sync"] = True
    if health_fail:
        settings["health_fail"] = True
    if close_error is not None:
        settings["close_error"] = close_error
    return RuntimeMessagingClientProfileSpec(
        client_profile_id=client_profile_id,
        tenant_id=_TENANT_ID,
        platform_key="matrix",
        profile_key=profile_key,
        config=build_config_namespace(
            {
                "basedir": "/tmp/mugen",
                "matrix": settings,
            }
        ),
        snapshot={
            "id": str(client_profile_id),
            "profile_key": profile_key,
            "room_id": settings["room_id"],
            "device": settings["client"]["device"],
            "displayname": displayname,
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
        if platform_key != "matrix":
            return ()
        index = min(self.calls, max(len(self._responses) - 1, 0))
        self.calls += 1
        return self._responses[index] if self._responses else ()


class _FakeManagedMatrixClient:
    instances: list["_FakeManagedMatrixClient"] = []

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        matrix_cfg = config.matrix
        self._config = config
        self.client_profile_id = str(matrix_cfg.client_profile_id)
        self.client_profile_key = str(matrix_cfg.client_profile_key)
        self.current_user_id = matrix_cfg.client.user
        self.device_id = getattr(matrix_cfg.client, "device", f"device-{self.client_profile_key}")
        self.sync_token = f"sync-{self.client_profile_key}"
        self.synced = asyncio.Event()
        self._stop = asyncio.Event()
        self.entered = False
        self.closed = False
        self.fail_before_sync = bool(getattr(matrix_cfg, "fail_before_sync", False))
        self.return_before_sync = bool(
            getattr(matrix_cfg, "return_before_sync", False)
        )
        self.health_fail = bool(getattr(matrix_cfg, "health_fail", False))
        self.close_error = getattr(matrix_cfg, "close_error", None)
        self.displayname = str(getattr(matrix_cfg, "profile_displayname", ""))
        self.rooms = [str(getattr(matrix_cfg, "room_id", f"!{self.client_profile_key}:test"))]
        self.direct_ids = set(self.rooms)
        self.process_ingress_event = AsyncMock()
        self.download_ingress_media = AsyncMock(
            side_effect=lambda event: {
                "client_profile_id": self.client_profile_id,
                "event": dict(event),
            }
        )
        self.emit_ingress_processing_signal = AsyncMock()
        self.send_ingress_responses = AsyncMock()
        self.set_displayname = AsyncMock(side_effect=self._set_displayname)
        self.trust_known_user_devices = AsyncMock()
        self.cleanup_known_user_devices_list = AsyncMock()
        self.verify_user_devices = AsyncMock()
        self.room_kick = AsyncMock()
        self.room_leave = AsyncMock()
        _FakeManagedMatrixClient.instances.append(self)

    async def __aenter__(self):
        self.entered = True
        return self

    async def close(self) -> None:
        self.closed = True
        self._stop.set()
        if isinstance(self.close_error, str) and self.close_error:
            raise RuntimeError(self.close_error)

    async def sync_forever(self, **_kwargs) -> None:
        if self.fail_before_sync:
            raise RuntimeError("sync failed")
        if self.return_before_sync:
            return
        self.synced.set()
        await self._stop.wait()

    async def monitor_runtime_health(self) -> None:
        if self.health_fail:
            raise RuntimeError("health failed")
        await self._stop.wait()

    async def get_profile(self, _user_id: str | None = None):
        return SimpleNamespace(displayname=self.displayname)

    async def _set_displayname(self, displayname: str) -> None:
        self.displayname = displayname

    def _resolve_profile_display_name(self) -> str | None:
        value = getattr(self._config.matrix, "profile_displayname", None)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    async def joined_room_ids(self) -> list[str]:
        return list(self.rooms)

    async def joined_member_ids(self, room_id: str) -> list[str]:
        return [f"{room_id}-member"]

    async def room_state_events(self, room_id: str) -> list[dict[str, str]]:
        return [{"room_id": room_id}]

    async def direct_room_ids(self) -> set[str]:
        return set(self.direct_ids)

    def device_ed25519_key(self) -> str:
        return f"ed25519-{self.client_profile_key}"


class TestMuGenMultiProfileMatrixClient(unittest.IsolatedAsyncioTestCase):
    """Covers Matrix multi-profile lifecycle, routing, and recovery logic."""

    def setUp(self) -> None:
        _FakeManagedMatrixClient.instances.clear()

    async def test_service_helper_empty_clients_and_default_client_requirements(
        self,
    ) -> None:
        imported_service_class = object()
        with (
            patch.object(matrix_mod, "MessagingClientProfileService", None),
            patch.object(
                matrix_mod.importlib,
                "import_module",
                return_value=SimpleNamespace(
                    MessagingClientProfileService=imported_service_class
                ),
            ) as import_module,
        ):
            self.assertIs(
                matrix_mod._messaging_client_profile_service_class(),  # pylint: disable=protected-access
                imported_service_class,
            )
        import_module.assert_called_once_with(
            "mugen.core.plugin.acp.service.messaging_client_profile"
        )

        client = matrix_mod.MultiProfileMatrixClient(config=_root_config())
        await client.init()
        self.assertEqual(client.managed_clients(), {})
        self.assertEqual(client.sync_token, "")
        self.assertEqual(client.current_user_id, "")
        self.assertEqual(client.device_id, "")
        self.assertEqual(client.device_ed25519_key(), "")
        sync_tasks, health_tasks = await client._prepare_client_set(  # pylint: disable=protected-access
            {},
            generation=1,
        )
        self.assertEqual(sync_tasks, {})
        self.assertEqual(health_tasks, {})
        self.assertTrue(client.synced.is_set())
        with self.assertRaisesRegex(RuntimeError, "No active client profiles"):
            await client.get_profile()

        default_client = object.__new__(matrix_mod.DefaultMatrixClient)
        default_client._config = SimpleNamespace(matrix=SimpleNamespace())
        with self.assertRaisesRegex(RuntimeError, "client_profile_id is required"):
            default_client._resolve_client_profile_id()  # pylint: disable=protected-access

    async def test_basic_fanout_properties_and_room_routing_helpers(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    device="device-default",
                    room_id="!default:test",
                ),
                _matrix_spec(
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                    user="@bot-secondary:example.com",
                    device="device-secondary",
                    room_id="!secondary:test",
                    displayname="Assistant",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            managed = client.managed_clients()
            first = managed[str(_DEFAULT_ID)]
            second = managed[str(_SECONDARY_ID)]

            self.assertEqual(sorted(managed.keys()), [str(_DEFAULT_ID), str(_SECONDARY_ID)])
            self.assertEqual(client.sync_token, "sync-default")
            self.assertEqual(client.current_user_id, "@bot-default:example.com")
            self.assertEqual(client.device_id, "device-default")
            self.assertEqual(client.device_ed25519_key(), "ed25519-default")
            first.device_ed25519_key = "not-callable"
            self.assertEqual(client.device_ed25519_key(), "")

            self.assertEqual(
                (await client.get_profile(user_id="@bot-secondary:example.com")).displayname,
                "Assistant",
            )
            self.assertEqual((await client.get_profile()).displayname, "")

            await client.set_displayname("Renamed")
            self.assertEqual(first.displayname, "Renamed")
            self.assertEqual(second.displayname, "Renamed")

            client._failure_queue.put_nowait(RuntimeError("runtime boom"))  # pylint: disable=protected-access
            with self.assertRaisesRegex(RuntimeError, "runtime boom"):
                await client.monitor_runtime_health()

            await client.cleanup_known_user_devices_list()
            await client.trust_known_user_devices()
            await client.verify_user_devices("@alice:test")
            first.cleanup_known_user_devices_list.assert_awaited()
            second.trust_known_user_devices.assert_awaited()
            second.verify_user_devices.assert_awaited_once_with("@alice:test")

            self.assertEqual(
                await client.joined_room_ids(),
                ["!default:test", "!secondary:test"],
            )
            self.assertEqual(
                await client.joined_member_ids("!secondary:test"),
                ["!secondary:test-member"],
            )
            self.assertEqual(
                await client.joined_member_ids("!missing:test"),
                ["!missing:test-member"],
            )
            self.assertEqual(
                await client.room_state_events("!secondary:test"),
                [{"room_id": "!secondary:test"}],
            )
            self.assertEqual(
                await client.room_state_events("!missing:test"),
                [{"room_id": "!missing:test"}],
            )
            self.assertEqual(
                await client.direct_room_ids(),
                {"!default:test", "!secondary:test"},
            )

            await client.room_kick("!secondary:test", "@user:test")
            second.room_kick.assert_awaited_once_with("!secondary:test", "@user:test")
            await client.room_kick("!missing:test", "@user:test")
            first.room_kick.assert_awaited_once_with("!missing:test", "@user:test")

            await client.room_leave("!secondary:test")
            second.room_leave.assert_awaited_once_with("!secondary:test")
            await client.room_leave("!missing:test")
            first.room_leave.assert_awaited_once_with("!missing:test")

            with self.assertRaisesRegex(RuntimeError, "run_profiles_forever"):
                await client.sync_forever()

    async def test_context_entry_prepare_reload_and_close(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    room_id="!default:test",
                ),
                _matrix_spec(
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                    user="@bot-secondary:example.com",
                    room_id="!secondary:test",
                    displayname="Assistant",
                ),
            ),
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    room_id="!default-updated:test",
                ),
                _matrix_spec(
                    client_profile_id=_TERTIARY_ID,
                    profile_key="tertiary",
                    user="@bot-tertiary:example.com",
                    room_id="!tertiary:test",
                    displayname="Assistant",
                ),
            ),
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            current_clients = tuple(client.managed_clients().values())

            entered = await client.__aenter__()
            self.assertIs(entered, client)
            self.assertTrue(all(item.entered for item in current_clients))

            sync_tasks, health_tasks = await client._prepare_client_set(  # pylint: disable=protected-access
                client._clients,  # pylint: disable=protected-access
                generation=1,
            )
            self.assertEqual(
                set(sync_tasks.keys()),
                {str(_DEFAULT_ID), str(_SECONDARY_ID)},
            )
            self.assertEqual(
                set(health_tasks.keys()),
                {str(_DEFAULT_ID), str(_SECONDARY_ID)},
            )
            self.assertEqual(current_clients[0].set_displayname.await_count, 0)
            self.assertEqual(current_clients[1].set_displayname.await_count, 0)

            client._generation = 1  # pylint: disable=protected-access
            client._sync_tasks = sync_tasks  # pylint: disable=protected-access
            client._health_tasks = health_tasks  # pylint: disable=protected-access

            diff = await client.reload_profiles(_root_config())
            self.assertEqual(diff["added"], [str(_TERTIARY_ID)])
            self.assertEqual(diff["removed"], [str(_SECONDARY_ID)])
            self.assertEqual(diff["updated"], [str(_DEFAULT_ID)])
            self.assertEqual(diff["unchanged"], [])
            self.assertTrue(all(item.closed for item in current_clients))
            self.assertTrue(client.synced.is_set())

            result = await client.__aexit__(None, None, None)
            self.assertFalse(result)
            self.assertFalse(client._entered)  # pylint: disable=protected-access
            await client.close()

    async def test_prepare_client_set_applies_profile_display_name_from_acp(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    displayname="Assistant",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            managed = client.managed_clients()[str(_DEFAULT_ID)]
            managed.displayname = ""

            await client._prepare_client_set(  # pylint: disable=protected-access
                client._clients,  # pylint: disable=protected-access
                generation=1,
            )

            managed.set_displayname.assert_awaited_once_with("Assistant")

    async def test_bind_runtime_task_callbacks_and_async_clear_branch(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            managed = client.managed_clients()[str(_DEFAULT_ID)]

            class _AsyncSynced:
                def __init__(self) -> None:
                    self.clear = AsyncMock()
                    self.wait = AsyncMock(return_value=None)

                def set(self) -> None:
                    return None

            managed.synced = _AsyncSynced()
            sync_tasks, health_tasks = await client._prepare_client_set(  # pylint: disable=protected-access
                client._clients,  # pylint: disable=protected-access
                generation=1,
            )
            managed.synced.clear.assert_awaited_once()
            await client._cancel_runtime_tasks(  # pylint: disable=protected-access
                sync_tasks,
                health_tasks,
            )
            managed.synced = SimpleNamespace(
                wait=AsyncMock(return_value=None),
                set=Mock(),
            )
            sync_tasks, health_tasks = await client._prepare_client_set(  # pylint: disable=protected-access
                client._clients,  # pylint: disable=protected-access
                generation=2,
            )
            await client._cancel_runtime_tasks(  # pylint: disable=protected-access
                sync_tasks,
                health_tasks,
            )

        callback_client = matrix_mod.MultiProfileMatrixClient(config=_root_config())
        callback_client._generation = 7  # pylint: disable=protected-access
        success_task = asyncio.create_task(asyncio.sleep(0))
        callback_client._bind_runtime_task(  # pylint: disable=protected-access
            success_task,
            generation=7,
            client_profile_id=str(_DEFAULT_ID),
            kind="sync",
        )
        await success_task
        await asyncio.sleep(0)
        error = callback_client._failure_queue.get_nowait()  # pylint: disable=protected-access
        self.assertIn("exited unexpectedly", str(error))

        cancelled_task = asyncio.create_task(asyncio.sleep(10))
        callback_client._bind_runtime_task(  # pylint: disable=protected-access
            cancelled_task,
            generation=7,
            client_profile_id=str(_DEFAULT_ID),
            kind="health",
        )
        cancelled_task.cancel()
        await asyncio.gather(cancelled_task, return_exceptions=True)
        await asyncio.sleep(0)
        self.assertTrue(callback_client._failure_queue.empty())  # pylint: disable=protected-access

        class _FakeTask:
            def __init__(self, *, error=None, raises_cancelled: bool = False) -> None:
                self._error = error
                self._raises_cancelled = raises_cancelled
                self._callback = None

            def add_done_callback(self, callback) -> None:
                self._callback = callback

            def cancelled(self) -> bool:
                return False

            def exception(self):
                if self._raises_cancelled:
                    raise asyncio.CancelledError()
                return self._error

            def fire(self) -> None:
                self._callback(self)

        exceptional_task = _FakeTask(error=RuntimeError("boom"))
        callback_client._bind_runtime_task(  # pylint: disable=protected-access
            exceptional_task,
            generation=7,
            client_profile_id=str(_DEFAULT_ID),
            kind="sync",
        )
        exceptional_task.fire()
        self.assertEqual(
            str(callback_client._failure_queue.get_nowait()),  # pylint: disable=protected-access
            "boom",
        )

        cancelled_error_task = _FakeTask(raises_cancelled=True)
        callback_client._bind_runtime_task(  # pylint: disable=protected-access
            cancelled_error_task,
            generation=7,
            client_profile_id=str(_DEFAULT_ID),
            kind="health",
        )
        cancelled_error_task.fire()
        self.assertTrue(callback_client._failure_queue.empty())  # pylint: disable=protected-access

    async def test_prepare_client_set_failure_and_auth_failure_paths(self) -> None:
        failing_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    fail_before_sync=True,
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=failing_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                await client._prepare_client_set(  # pylint: disable=protected-access
                    client._clients,  # pylint: disable=protected-access
                    generation=1,
                )

        healthy_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=healthy_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            client._prepare_client_set = AsyncMock(  # type: ignore[method-assign]
                side_effect=RuntimeError("M_UNKNOWN_TOKEN")
            )
            with self.assertRaisesRegex(RuntimeError, "authentication failed"):
                await client.run_profiles_forever()

    async def test_ingress_methods_route_by_client_profile_or_first_client(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
                _matrix_spec(
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                    user="@bot-secondary:example.com",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            first = client.managed_clients()[str(_DEFAULT_ID)]
            second = client.managed_clients()[str(_SECONDARY_ID)]

            event = {"client_profile_id": str(_SECONDARY_ID), "event_id": "$secondary"}
            await client.process_ingress_event(event)
            second.process_ingress_event.assert_awaited_once_with(event)

            fallback_event = {"client_profile_id": str(_TERTIARY_ID), "event_id": "$fallback"}
            await client.process_ingress_event(fallback_event)
            first.process_ingress_event.assert_awaited_once_with(fallback_event)

            media_result = await client.download_ingress_media(
                {"client_profile_id": str(_SECONDARY_ID), "event_id": "$secondary"}
            )
            self.assertEqual(media_result["client_profile_id"], str(_SECONDARY_ID))

            fallback_media = await client.download_ingress_media(
                {"client_profile_id": str(_TERTIARY_ID), "event_id": "$fallback"}
            )
            self.assertEqual(fallback_media["client_profile_id"], str(_DEFAULT_ID))
            await client.process_ingress_event("not-a-dict")
            first.process_ingress_event.assert_awaited_with("not-a-dict")

            fallback_profile = await client.get_profile(user_id="@missing:example.com")
            self.assertEqual(fallback_profile.displayname, "")

            await client.emit_ingress_processing_signal("!fallback:test", state="start")
            first.emit_ingress_processing_signal.assert_awaited_once_with(
                "!fallback:test",
                state="start",
            )
            await client.send_ingress_responses("!fallback:test", [{"content": "ok"}])
            first.send_ingress_responses.assert_awaited_once_with(
                "!fallback:test",
                [{"content": "ok"}],
            )
            fallback_media_non_dict = await client.download_ingress_media(
                [("event_id", "$fallback")]
            )
            self.assertEqual(fallback_media_non_dict["client_profile_id"], str(_DEFAULT_ID))

    async def test_empty_and_reload_diff_paths(self) -> None:
        empty_service = _MessagingClientProfileServiceStub(())
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=empty_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            self.assertEqual(client.managed_clients(), {})
            self.assertEqual(client.current_user_id, "")
            self.assertEqual(client.device_id, "")
            self.assertEqual(client.device_ed25519_key(), "")
            with self.assertRaisesRegex(RuntimeError, "No active client profiles"):
                await client.get_profile()

        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    room_id="!default:test",
                ),
            ),
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    room_id="!default-updated:test",
                ),
            ),
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            diff = await client.reload_profiles(_root_config())
            self.assertEqual(diff["added"], [])
            self.assertEqual(diff["removed"], [])
            self.assertEqual(diff["updated"], [str(_DEFAULT_ID)])
            self.assertEqual(diff["unchanged"], [])

    async def test_run_profiles_forever_success_no_clients_and_retry_paths(self) -> None:
        empty_client = matrix_mod.MultiProfileMatrixClient(config=_root_config())
        started: list[str] = []
        healthy: list[str] = []
        with patch.object(
            matrix_mod.asyncio,
            "sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await empty_client.run_profiles_forever(
                    started_callback=lambda: started.append("started"),
                    healthy_callback=lambda: healthy.append("healthy"),
                )
        self.assertEqual(started, ["started"])
        self.assertEqual(healthy, ["healthy"])

        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            started = []
            healthy = []
            task = asyncio.create_task(
                client.run_profiles_forever(
                    started_callback=lambda: started.append("started"),
                    healthy_callback=lambda: healthy.append("healthy"),
                )
            )
            await asyncio.wait_for(client.synced.wait(), timeout=1)
            client._failure_queue.put_nowait(  # pylint: disable=protected-access
                matrix_mod.IPCCriticalDispatchError(
                    platform="matrix",
                    command="matrix_ingress_event",
                    handler="handler-a",
                    code="critical",
                    error="critical runtime failure",
                )
            )
            with self.assertRaises(matrix_mod.IPCCriticalDispatchError):
                await task
            self.assertEqual(started, ["started"])
            self.assertEqual(healthy, ["healthy"])

        failure_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    health_fail=True,
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=failure_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            degraded: list[str] = []
            with patch.object(
                matrix_mod.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await client.run_profiles_forever(
                        degraded_callback=degraded.append,
                    )
            self.assertEqual(len(degraded), 1)
            self.assertIn("health failed", degraded[0])

        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            client._prepare_client_set = AsyncMock(  # type: ignore[method-assign]
                side_effect=matrix_mod.IPCCriticalDispatchError(
                    platform="matrix",
                    command="matrix_ingress_event",
                    handler="handler-a",
                    code="critical",
                    error="critical prepare failure",
                )
            )
            with self.assertRaises(matrix_mod.IPCCriticalDispatchError):
                await client.run_profiles_forever()

        retry_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    fail_before_sync=True,
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=retry_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
            patch.object(
                matrix_mod.asyncio,
                "sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with self.assertRaisesRegex(RuntimeError, "after max retries"):
                await client.run_profiles_forever()

    async def test_run_profiles_forever_empty_branch_continue_and_recovery(self) -> None:
        empty_client = matrix_mod.MultiProfileMatrixClient(config=_root_config())
        sleep_calls = 0

        async def _empty_sleep(_seconds: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 1:
                return None
            raise asyncio.CancelledError()

        healthy: list[str] = []
        with patch.object(
            matrix_mod.asyncio,
            "sleep",
            new=AsyncMock(side_effect=_empty_sleep),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await empty_client.run_profiles_forever(
                    healthy_callback=lambda: healthy.append("healthy"),
                )
        self.assertEqual(healthy, ["healthy"])

        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            client._prepare_client_set = AsyncMock(return_value=({}, {}))  # type: ignore[method-assign]
            healthy = []
            degraded = []
            sleep_calls = 0

            async def _recovery_sleep(_seconds: float) -> None:
                nonlocal sleep_calls
                sleep_calls += 1
                if sleep_calls == 1:
                    client._clients = {}  # pylint: disable=protected-access
                    return None
                raise asyncio.CancelledError()

            with patch.object(
                matrix_mod.asyncio,
                "sleep",
                new=AsyncMock(side_effect=_recovery_sleep),
            ):
                task = asyncio.create_task(
                    client.run_profiles_forever(
                        degraded_callback=degraded.append,
                        healthy_callback=lambda: healthy.append("healthy"),
                    )
                )
                await asyncio.wait_for(client.synced.wait(), timeout=1)
                client._failure_queue.put_nowait(RuntimeError("boom"))  # pylint: disable=protected-access
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(degraded, ["RuntimeError: boom"])
            self.assertEqual(healthy, ["healthy", "healthy"])

    async def test_run_profiles_forever_empty_branch_without_healthy_callback(
        self,
    ) -> None:
        empty_client = matrix_mod.MultiProfileMatrixClient(config=_root_config())
        started: list[str] = []
        with patch.object(
            matrix_mod.asyncio,
            "sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError()),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await empty_client.run_profiles_forever(
                    started_callback=lambda: started.append("started"),
                )
        self.assertEqual(started, ["started"])

    async def test_run_profiles_forever_success_without_callbacks_and_recovery(
        self,
    ) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            client._prepare_client_set = AsyncMock(  # type: ignore[method-assign]
                side_effect=[({}, {}), ({}, {})]
            )

            task = asyncio.create_task(client.run_profiles_forever())
            await asyncio.wait_for(client.synced.wait(), timeout=1)
            client._failure_queue.put_nowait(RuntimeError("boom"))  # pylint: disable=protected-access
            for _ in range(20):
                if client._prepare_client_set.await_count >= 2:  # type: ignore[union-attr]
                    break
                await asyncio.sleep(0)
            client._failure_queue.put_nowait(  # pylint: disable=protected-access
                matrix_mod.IPCCriticalDispatchError(
                    platform="matrix",
                    command="matrix_ingress_event",
                    handler="handler-a",
                    code="critical",
                    error="critical runtime failure",
                )
            )
            with self.assertRaises(matrix_mod.IPCCriticalDispatchError):
                await task

        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            client._prepare_client_set = AsyncMock(  # type: ignore[method-assign]
                side_effect=[({}, {}), ({}, {})]
            )
            healthy: list[str] = []
            degraded: list[str] = []
            with patch.object(
                matrix_mod.asyncio,
                "sleep",
                new=AsyncMock(return_value=None),
            ):
                task = asyncio.create_task(
                    client.run_profiles_forever(
                        degraded_callback=degraded.append,
                        healthy_callback=lambda: healthy.append("healthy"),
                    )
                )
                await asyncio.wait_for(client.synced.wait(), timeout=1)
                client._failure_queue.put_nowait(RuntimeError("boom"))  # pylint: disable=protected-access
                for _ in range(20):
                    if len(healthy) >= 2:
                        break
                    await asyncio.sleep(0)
                client._failure_queue.put_nowait(  # pylint: disable=protected-access
                    matrix_mod.IPCCriticalDispatchError(
                        platform="matrix",
                        command="matrix_ingress_event",
                        handler="handler-a",
                        code="critical",
                        error="critical runtime failure",
                    )
                )
                with self.assertRaises(matrix_mod.IPCCriticalDispatchError):
                    await task
            self.assertEqual(degraded, ["RuntimeError: boom"])
            self.assertEqual(healthy, ["healthy", "healthy"])

    async def test_prepare_failure_without_exception_and_reload_cleanup_failure(self) -> None:
        return_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    return_before_sync=True,
                ),
            )
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=return_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            with self.assertRaisesRegex(
                RuntimeError,
                "before initial sync",
            ):
                await client._prepare_client_set(  # pylint: disable=protected-access
                    client._clients,  # pylint: disable=protected-access
                    generation=1,
                )

        cleanup_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            ),
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    fail_before_sync=True,
                    close_error="reload close failed",
                ),
            ),
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=cleanup_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            await client.__aenter__()
            entered_again = await client.__aenter__()
            self.assertIs(entered_again, client)
            with self.assertRaisesRegex(
                RuntimeError,
                "cleanup failed",
            ):
                await client.reload_profiles(_root_config())
            await client.close()

    async def test_reload_profiles_reraises_original_error_after_cleanup(self) -> None:
        reload_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            ),
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    fail_before_sync=True,
                ),
            ),
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=reload_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            await client.__aenter__()
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                await client.reload_profiles(_root_config())
            await client.close()

    async def test_reload_profiles_reraises_original_error_when_not_entered(
        self,
    ) -> None:
        reload_service = _MessagingClientProfileServiceStub(
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                ),
            ),
            (
                _matrix_spec(
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    user="@bot-default:example.com",
                    fail_before_sync=True,
                ),
            ),
        )
        with (
            patch.object(
                matrix_mod,
                "MessagingClientProfileService",
                return_value=reload_service,
            ),
            patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient),
        ):
            client = matrix_mod.MultiProfileMatrixClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await client.init()
            with patch.object(
                matrix_mod.MultiProfileMatrixClient,
                "_generation",
                create=True,
                new_callable=PropertyMock,
                side_effect=RuntimeError("generation failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "generation failed"):
                    await client.reload_profiles(_root_config())
            await client.close()
