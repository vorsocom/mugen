"""Unit tests for matrix multi-profile client management."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.client import matrix as matrix_mod
from mugen.core.contract.service.ipc import IPCCriticalDispatchError
from mugen.core.utility.platform_runtime_profile import build_config_namespace


def _matrix_config(*profiles: dict) -> SimpleNamespace:
    return build_config_namespace(
        {
            "basedir": "/tmp/mugen",
            "matrix": {
                "assistant": {"name": "Assistant"},
                "profiles": list(profiles),
            },
        }
    )


class _FakeManagedMatrixClient:
    instances: list["_FakeManagedMatrixClient"] = []

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        matrix_cfg = config.matrix
        self._config = config
        self.runtime_profile_key = matrix_cfg.runtime_profile_key
        self.current_user_id = matrix_cfg.client.user
        self.device_id = getattr(matrix_cfg.client, "device", f"device-{self.runtime_profile_key}")
        self.sync_token = f"sync-{self.runtime_profile_key}"
        self.synced = asyncio.Event()
        self._stop = asyncio.Event()
        self.entered = False
        self.closed = False
        self.fail_before_sync = bool(getattr(matrix_cfg, "fail_before_sync", False))
        self.health_fail = bool(getattr(matrix_cfg, "health_fail", False))
        self.close_error = getattr(matrix_cfg, "close_error", None)
        self.displayname = str(getattr(matrix_cfg, "profile_displayname", ""))
        room_id = str(getattr(matrix_cfg, "room_id", f"!{self.runtime_profile_key}:test"))
        self.rooms = [room_id]
        self.direct_ids = {room_id}
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

    async def joined_room_ids(self) -> list[str]:
        return list(self.rooms)

    async def joined_member_ids(self, room_id: str) -> list[str]:
        return [f"{room_id}-member"]

    async def room_state_events(self, room_id: str) -> list[dict[str, str]]:
        return [{"room_id": room_id}]

    async def direct_room_ids(self) -> set[str]:
        return set(self.direct_ids)

    def device_ed25519_key(self) -> str:
        return f"ed25519-{self.runtime_profile_key}"


class TestMuGenMultiProfileMatrixClient(unittest.IsolatedAsyncioTestCase):
    """Covers Matrix multi-profile lifecycle, routing, and recovery logic."""

    def setUp(self) -> None:
        _FakeManagedMatrixClient.instances.clear()

    async def test_basic_fanout_properties_and_room_routing_helpers(self) -> None:
        config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com", "device": "device-default"},
                "profile_displayname": "",
                "room_id": "!default:test",
            },
            {
                "key": "secondary",
                "client": {"user": "@bot-secondary:example.com", "device": "device-secondary"},
                "profile_displayname": "Assistant",
                "room_id": "!secondary:test",
            },
        )
        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            client = matrix_mod.MultiProfileMatrixClient(config=config)
            managed = client.managed_clients()
            first = managed["default"]
            second = managed["secondary"]

            self.assertEqual(sorted(managed.keys()), ["default", "secondary"])
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
        config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
                "profile_displayname": "",
                "room_id": "!default:test",
            },
            {
                "key": "secondary",
                "client": {"user": "@bot-secondary:example.com"},
                "profile_displayname": "Assistant",
                "room_id": "!secondary:test",
            },
        )
        next_config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
                "profile_displayname": "",
                "room_id": "!default-updated:test",
            },
            {
                "key": "tertiary",
                "client": {"user": "@bot-tertiary:example.com"},
                "profile_displayname": "Assistant",
                "room_id": "!tertiary:test",
            },
        )

        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            client = matrix_mod.MultiProfileMatrixClient(config=config)
            current_clients = tuple(client.managed_clients().values())

            entered = await client.__aenter__()
            self.assertIs(entered, client)
            self.assertTrue(all(item.entered for item in current_clients))

            sync_tasks, health_tasks = await client._prepare_client_set(  # pylint: disable=protected-access
                client._clients,  # pylint: disable=protected-access
                generation=1,
            )
            self.assertEqual(set(sync_tasks.keys()), {"default", "secondary"})
            self.assertEqual(set(health_tasks.keys()), {"default", "secondary"})
            self.assertEqual(current_clients[0].set_displayname.await_count, 1)
            self.assertEqual(current_clients[1].set_displayname.await_count, 0)

            client._generation = 1  # pylint: disable=protected-access
            client._sync_tasks = sync_tasks  # pylint: disable=protected-access
            client._health_tasks = health_tasks  # pylint: disable=protected-access

            diff = await client.reload_profiles(next_config)
            self.assertEqual(diff["added"], ["tertiary"])
            self.assertEqual(diff["removed"], ["secondary"])
            self.assertEqual(diff["updated"], ["default"])
            self.assertEqual(diff["unchanged"], [])
            self.assertTrue(all(item.closed for item in current_clients))
            self.assertTrue(client.synced.is_set())

            result = await client.__aexit__(None, None, None)
            self.assertFalse(result)
            self.assertFalse(client._entered)  # pylint: disable=protected-access
            await client._cancel_runtime_tasks({}, {})  # pylint: disable=protected-access
            await client.close()

    async def test_prepare_client_set_failure_auth_failure_and_retry_paths(self) -> None:
        failing_config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
                "fail_before_sync": True,
            }
        )
        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            client = matrix_mod.MultiProfileMatrixClient(config=failing_config)
            with self.assertRaisesRegex(RuntimeError, "sync failed"):
                await client._prepare_client_set(  # pylint: disable=protected-access
                    client._clients,  # pylint: disable=protected-access
                    generation=1,
                )

        normal_config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
            }
        )
        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            auth_client = matrix_mod.MultiProfileMatrixClient(config=normal_config)
            with patch.object(
                auth_client,
                "_prepare_client_set",
                new=AsyncMock(side_effect=RuntimeError("M_UNKNOWN_TOKEN")),
            ):
                with self.assertRaisesRegex(RuntimeError, "authentication failed"):
                    await auth_client.run_profiles_forever()

            recovering_client = matrix_mod.MultiProfileMatrixClient(config=normal_config)
            real_sleep = asyncio.sleep
            second_generation_started = asyncio.Event()
            task_holders: list[tuple[dict[str, asyncio.Task], dict[str, asyncio.Task]]] = []

            async def _prepare(_clients, generation):
                sync_event = asyncio.Event()
                health_event = asyncio.Event()
                sync_tasks = {
                    "default": asyncio.create_task(
                        sync_event.wait(),
                        name=f"sync-{generation}",
                    )
                }
                health_tasks = {
                    "default": asyncio.create_task(
                        health_event.wait(),
                        name=f"health-{generation}",
                    )
                }
                task_holders.append((sync_tasks, health_tasks))
                if generation > 1:
                    second_generation_started.set()
                return sync_tasks, health_tasks

            started_callback = Mock()
            degraded_callback = Mock()
            healthy_callback = Mock()

            async def _fast_sleep(_delay: float) -> None:
                await real_sleep(0)

            with (
                patch.object(
                    recovering_client,
                    "_prepare_client_set",
                    new=AsyncMock(side_effect=_prepare),
                ),
                patch.object(matrix_mod.random, "uniform", return_value=-1.0),
                patch.object(matrix_mod.asyncio, "sleep", side_effect=_fast_sleep),
            ):
                runner = asyncio.create_task(
                    recovering_client.run_profiles_forever(
                        started_callback=started_callback,
                        degraded_callback=degraded_callback,
                        healthy_callback=healthy_callback,
                    )
                )

                while started_callback.call_count == 0:
                    await real_sleep(0)
                recovering_client._failure_queue.put_nowait(  # pylint: disable=protected-access
                    RuntimeError("transient failure")
                )
                await asyncio.wait_for(second_generation_started.wait(), timeout=1)
                self.assertEqual(started_callback.call_count, 1)
                self.assertEqual(degraded_callback.call_count, 1)
                self.assertEqual(healthy_callback.call_count, 2)

                runner.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await runner

            for sync_tasks, health_tasks in task_holders:
                await asyncio.gather(
                    *sync_tasks.values(),
                    *health_tasks.values(),
                    return_exceptions=True,
                )

            retry_client = matrix_mod.MultiProfileMatrixClient(config=normal_config)
            with (
                patch.object(
                    retry_client,
                    "_prepare_client_set",
                    new=AsyncMock(side_effect=RuntimeError("boom")),
                ),
                patch.object(matrix_mod.random, "uniform", return_value=-1.0),
                patch.object(matrix_mod.asyncio, "sleep", side_effect=_fast_sleep),
            ):
                degraded_callback = Mock()
                with self.assertRaisesRegex(RuntimeError, "max retries"):
                    await retry_client.run_profiles_forever(
                        degraded_callback=degraded_callback,
                    )
                degraded_callback.assert_called_once()

    async def test_private_matrix_manager_edge_paths(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "No matrix runtime profiles configured"):
            matrix_mod.MultiProfileMatrixClient(
                config=build_config_namespace({"basedir": "/tmp/mugen"})
            )

        config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
                "profile_displayname": "",
                "room_id": "!default:test",
            }
        )

        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            client = matrix_mod.MultiProfileMatrixClient(config=config)

            self.assertEqual(
                (await client.get_profile(user_id="@missing:example.com")).displayname,
                "",
            )

            client._clients = {}  # pylint: disable=protected-access
            self.assertEqual(client.sync_token, "")

        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            callback_client = matrix_mod.MultiProfileMatrixClient(config=config)

            class _CallbackTask:
                def __init__(self, *, cancelled=False, error=None) -> None:
                    self._cancelled = cancelled
                    self._error = error
                    self.callback = None

                def add_done_callback(self, callback) -> None:
                    self.callback = callback

                def cancelled(self) -> bool:
                    return self._cancelled

                def exception(self):
                    if isinstance(self._error, asyncio.CancelledError):
                        raise self._error
                    if isinstance(self._error, BaseException):
                        return self._error
                    return self._error

            done_task = _CallbackTask(error=None)
            callback_client._bind_runtime_task(  # pylint: disable=protected-access
                done_task,  # type: ignore[arg-type]
                generation=0,
                runtime_profile_key="default",
                kind="sync",
            )
            done_task.callback(done_task)
            runtime_error = await asyncio.wait_for(
                callback_client._failure_queue.get(),  # pylint: disable=protected-access
                timeout=1,
            )
            self.assertIn("exited unexpectedly", str(runtime_error))

            failing_task = _CallbackTask(error=RuntimeError("sync boom"))
            callback_client._bind_runtime_task(  # pylint: disable=protected-access
                failing_task,  # type: ignore[arg-type]
                generation=0,
                runtime_profile_key="default",
                kind="sync",
            )
            failing_task.callback(failing_task)
            queued_error = await asyncio.wait_for(
                callback_client._failure_queue.get(),  # pylint: disable=protected-access
                timeout=1,
            )
            self.assertEqual(str(queued_error), "sync boom")

            cancelled_task = _CallbackTask(cancelled=True)
            callback_client._bind_runtime_task(  # pylint: disable=protected-access
                cancelled_task,  # type: ignore[arg-type]
                generation=0,
                runtime_profile_key="default",
                kind="health",
            )
            cancelled_task.callback(cancelled_task)
            self.assertTrue(callback_client._failure_queue.empty())  # pylint: disable=protected-access

            cancelled_error_task = _CallbackTask(error=asyncio.CancelledError())
            callback_client._bind_runtime_task(  # pylint: disable=protected-access
                cancelled_error_task,  # type: ignore[arg-type]
                generation=0,
                runtime_profile_key="default",
                kind="health",
            )
            cancelled_error_task.callback(cancelled_error_task)
            self.assertTrue(callback_client._failure_queue.empty())  # pylint: disable=protected-access

    async def test_prepare_client_set_private_branch_paths(self) -> None:
        config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
            }
        )

        class _AwaitableSyncSignal:
            def __init__(self) -> None:
                self._event = asyncio.Event()
                self.clear_count = 0

            async def clear(self) -> None:
                self.clear_count += 1
                self._event.clear()

            async def wait(self) -> None:
                await self._event.wait()

            def set(self) -> None:
                self._event.set()

        class _SyncSignalNoClear:
            def __init__(self) -> None:
                self._event = asyncio.Event()

            async def wait(self) -> None:
                await self._event.wait()

            def set(self) -> None:
                self._event.set()

        class _PreparedClient:
            def __init__(self, synced, *, displayname: str = "") -> None:
                self.synced = synced
                self.sync_token = "sync-token"
                self.profile = SimpleNamespace(displayname=displayname)
                self._config = SimpleNamespace(
                    matrix=SimpleNamespace(assistant=SimpleNamespace(name="Assistant"))
                )
                self._stop = asyncio.Event()
                self.set_displayname = AsyncMock()
                self.trust_known_user_devices = AsyncMock()

            async def sync_forever(self, **_kwargs) -> None:
                self.synced.set()
                await self._stop.wait()

            async def monitor_runtime_health(self) -> None:
                await self._stop.wait()

            async def get_profile(self):
                return self.profile

        class _EarlyExitClient(_PreparedClient):
            async def sync_forever(self, **_kwargs) -> None:
                return None

        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            client = matrix_mod.MultiProfileMatrixClient(config=config)
            with_clear = _PreparedClient(_AwaitableSyncSignal(), displayname="")
            without_clear = _PreparedClient(_SyncSignalNoClear(), displayname="Assistant")
            sync_tasks, health_tasks = await client._prepare_client_set(  # pylint: disable=protected-access
                {
                    "default": with_clear,
                    "secondary": without_clear,
                },
                generation=1,
            )
            self.assertEqual(with_clear.synced.clear_count, 1)
            with_clear.set_displayname.assert_awaited_once_with("Assistant")
            without_clear.set_displayname.assert_not_awaited()
            await client._cancel_runtime_tasks(sync_tasks, health_tasks)  # pylint: disable=protected-access

            with self.assertRaisesRegex(
                RuntimeError,
                "before initial sync",
            ):
                await client._prepare_client_set(  # pylint: disable=protected-access
                    {"default": _EarlyExitClient(_AwaitableSyncSignal())},
                    generation=2,
                )

    async def test_run_profiles_forever_ipc_critical_and_reload_edge_paths(self) -> None:
        config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
                "profile_displayname": "",
                "room_id": "!default:test",
            }
        )
        next_config = _matrix_config(
            {
                "key": "default",
                "client": {"user": "@bot-default:example.com"},
                "profile_displayname": "",
                "room_id": "!default-updated:test",
            }
        )

        with patch.object(matrix_mod, "DefaultMatrixClient", _FakeManagedMatrixClient):
            no_task_client = matrix_mod.MultiProfileMatrixClient(config=config)
            diff = await no_task_client.reload_profiles(next_config)
            self.assertEqual(diff["updated"], ["default"])
            self.assertFalse(no_task_client.synced.is_set())

            entered_client = matrix_mod.MultiProfileMatrixClient(config=config)
            current_clients = tuple(entered_client.managed_clients().values())
            for managed_client in current_clients:
                managed_client.__aenter__ = AsyncMock(return_value=managed_client)

            await entered_client.__aenter__()
            await entered_client.__aenter__()
            for managed_client in current_clients:
                managed_client.__aenter__.assert_awaited_once()

            entered_client._sync_tasks = {  # pylint: disable=protected-access
                "default": asyncio.create_task(asyncio.Event().wait())
            }
            entered_client._health_tasks = {  # pylint: disable=protected-access
                "default": asyncio.create_task(asyncio.Event().wait())
            }

            before_instances = len(_FakeManagedMatrixClient.instances)
            with patch.object(
                entered_client,
                "_prepare_client_set",
                new=AsyncMock(side_effect=RuntimeError("reload failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "reload failed"):
                    await entered_client.reload_profiles(next_config)

            new_clients = _FakeManagedMatrixClient.instances[before_instances:]
            self.assertTrue(new_clients)
            self.assertTrue(all(item.entered for item in new_clients))
            self.assertTrue(all(item.closed for item in new_clients))
            await entered_client.close()

            not_entered_client = matrix_mod.MultiProfileMatrixClient(config=config)
            not_entered_client._sync_tasks = {  # pylint: disable=protected-access
                "default": asyncio.create_task(asyncio.Event().wait())
            }
            with patch.object(
                not_entered_client,
                "_prepare_client_set",
                new=AsyncMock(side_effect=RuntimeError("reload failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "reload failed"):
                    await not_entered_client.reload_profiles(next_config)
            await not_entered_client.close()

            cleanup_failure_client = matrix_mod.MultiProfileMatrixClient(config=config)
            await cleanup_failure_client.__aenter__()
            cleanup_failure_client._sync_tasks = {  # pylint: disable=protected-access
                "default": asyncio.create_task(asyncio.Event().wait())
            }
            cleanup_failure_client._health_tasks = {  # pylint: disable=protected-access
                "default": asyncio.create_task(asyncio.Event().wait())
            }
            failing_reload_config = _matrix_config(
                {
                    "key": "default",
                    "client": {"user": "@bot-default:example.com"},
                    "profile_displayname": "",
                    "room_id": "!default-updated:test",
                    "close_error": "candidate cleanup failed",
                }
            )
            with patch.object(
                cleanup_failure_client,
                "_prepare_client_set",
                new=AsyncMock(side_effect=RuntimeError("reload failed")),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    (
                        "matrix runtime profile reload failed after RuntimeError: "
                        "reload failed; cleanup failed: "
                        "matrix runtime profile cleanup failed: "
                        "default=RuntimeError: candidate cleanup failed"
                    ),
                ):
                    await cleanup_failure_client.reload_profiles(failing_reload_config)
            await cleanup_failure_client.close()

            retry_client = matrix_mod.MultiProfileMatrixClient(config=config)
            real_sleep = asyncio.sleep
            second_generation_started = asyncio.Event()
            task_holders: list[tuple[dict[str, asyncio.Task], dict[str, asyncio.Task]]] = []

            async def _prepare(_clients, generation):
                sync_event = asyncio.Event()
                health_event = asyncio.Event()
                sync_tasks = {
                    "default": asyncio.create_task(
                        sync_event.wait(),
                        name=f"sync-{generation}",
                    )
                }
                health_tasks = {
                    "default": asyncio.create_task(
                        health_event.wait(),
                        name=f"health-{generation}",
                    )
                }
                task_holders.append((sync_tasks, health_tasks))
                if generation > 1:
                    second_generation_started.set()
                return sync_tasks, health_tasks

            async def _fast_sleep(_delay: float) -> None:
                await real_sleep(0)

            started_callback = Mock()
            with (
                patch.object(
                    retry_client,
                    "_prepare_client_set",
                    new=AsyncMock(side_effect=_prepare),
                ),
                patch.object(matrix_mod.random, "uniform", return_value=-1.0),
                patch.object(matrix_mod.asyncio, "sleep", side_effect=_fast_sleep),
            ):
                runner = asyncio.create_task(
                    retry_client.run_profiles_forever(
                        started_callback=started_callback,
                    )
                )

                while started_callback.call_count == 0:
                    await real_sleep(0)
                retry_client._failure_queue.put_nowait(  # pylint: disable=protected-access
                    RuntimeError("transient failure")
                )
                await asyncio.wait_for(second_generation_started.wait(), timeout=1)
                runner.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await runner

            for sync_tasks, health_tasks in task_holders:
                await asyncio.gather(
                    *sync_tasks.values(),
                    *health_tasks.values(),
                    return_exceptions=True,
                )

            critical_client = matrix_mod.MultiProfileMatrixClient(config=config)

            async def _critical_prepare(_clients, generation):
                sync_tasks = {
                    "default": asyncio.create_task(
                        asyncio.Event().wait(),
                        name=f"critical-sync-{generation}",
                    )
                }
                health_tasks = {
                    "default": asyncio.create_task(
                        asyncio.Event().wait(),
                        name=f"critical-health-{generation}",
                    )
                }
                return sync_tasks, health_tasks

            healthy_callback = Mock()
            with patch.object(
                critical_client,
                "_prepare_client_set",
                new=AsyncMock(side_effect=_critical_prepare),
            ):
                runner = asyncio.create_task(
                    critical_client.run_profiles_forever(
                        healthy_callback=healthy_callback,
                    )
                )
                while healthy_callback.call_count == 0:
                    await real_sleep(0)
                critical_client._failure_queue.put_nowait(  # pylint: disable=protected-access
                    IPCCriticalDispatchError(
                        platform="matrix",
                        command="dispatch",
                        handler="handler",
                        code="critical",
                        error="stop now",
                    )
                )
                with self.assertRaises(IPCCriticalDispatchError):
                    await runner
