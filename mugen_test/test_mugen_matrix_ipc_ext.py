"""Unit tests for matrix IPC extensions."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from mugen.core.contract.service.ipc import IPCCommandRequest
import mugen.core.plugin.matrix.manager.device_ipc_ext as device_ipc_ext_module
import mugen.core.plugin.matrix.manager.room_ipc_ext as room_ipc_ext_module
from mugen.core.plugin.matrix.manager.device_ipc_ext import (
    DeviceManagementIPCExtension,
)
from mugen.core.plugin.matrix.manager.room_ipc_ext import (
    RoomManagementIPCExtension,
)


class _InMemoryKeyValStorageGateway:  # pylint: disable=too-few-public-methods
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self._values: dict[str, object] = dict(values or {})
        self.removed_keys: list[str] = []

    async def exists(self, key: str, *, namespace: str | None = None) -> bool:
        del namespace
        return key in self._values

    async def get_json(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> object | None:
        del namespace
        return self._values.get(key)

    async def delete(
        self,
        key: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
    ) -> object | None:
        del namespace
        del expected_row_version
        self.removed_keys.append(key)
        return self._values.pop(key, None)


class TestDeviceManagementIPCExtension(unittest.IsolatedAsyncioTestCase):
    """Tests for DeviceManagementIPCExtension."""

    async def test_process_ipc_command_returns_verification_data(self) -> None:
        ext = DeviceManagementIPCExtension(
            config=SimpleNamespace(
                matrix=SimpleNamespace(client=SimpleNamespace(device="Assistant Device"))
            ),
            matrix_client=SimpleNamespace(
                device_id="DEV-1234",
                olm=SimpleNamespace(
                    account=SimpleNamespace(identity_keys={"ed25519": "ABCD1234EFGH5678"})
                ),
            ),
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_get_device_verification_data",
                data={},
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.handler, "DeviceManagementIPCExtension")
        self.assertEqual(
            response.response,
            {
                "response": {
                    "data": {
                        "public_name": "Assistant Device",
                        "session_id": "DEV-1234",
                        "session_key": "ABCD 1234 EFGH 5678",
                    }
                }
            },
        )

    async def test_process_ipc_command_returns_not_found_for_unknown_command(
        self,
    ) -> None:
        ext = DeviceManagementIPCExtension(
            config=SimpleNamespace(matrix=SimpleNamespace(client=SimpleNamespace(device=""))),
            matrix_client=SimpleNamespace(device_id="", olm=SimpleNamespace(account=None)),
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="unknown_matrix_command",
                data={},
            )
        )

        self.assertFalse(response.ok)
        self.assertEqual(response.code, "not_found")
        self.assertEqual(response.error, "Unsupported IPC command.")

    async def test_constructor_fallback_and_session_key_guard_paths(self) -> None:
        container = SimpleNamespace(
            config=SimpleNamespace(matrix=SimpleNamespace(client=SimpleNamespace(device=""))),
            matrix_client=SimpleNamespace(
                device_id="",
                olm=SimpleNamespace(account=SimpleNamespace(identity_keys={})),
            ),
            logging_gateway=Mock(),
        )
        with patch.object(device_ipc_ext_module.di, "container", container):
            ext = DeviceManagementIPCExtension()

        self.assertEqual(ext.ipc_commands, ["matrix_get_device_verification_data"])
        self.assertEqual(ext.platforms, ["matrix"])

        ext._client = SimpleNamespace(  # pylint: disable=protected-access
            olm=SimpleNamespace(account=SimpleNamespace(identity_keys=[]))
        )
        self.assertEqual(ext._resolve_session_key(), "")  # pylint: disable=protected-access

        ext._client = SimpleNamespace(  # pylint: disable=protected-access
            olm=SimpleNamespace(account=SimpleNamespace(identity_keys={"ed25519": 1234}))
        )
        self.assertEqual(ext._resolve_session_key(), "")  # pylint: disable=protected-access


class TestRoomManagementIPCExtension(unittest.IsolatedAsyncioTestCase):
    """Tests for RoomManagementIPCExtension."""

    async def test_matrix_list_rooms_returns_normalized_room_details(self) -> None:
        keyval_storage_gateway = _InMemoryKeyValStorageGateway(
            {
                "chat_threads_list:!room-a:example.com": {
                    "threads": ["thread:1", "thread:2", 99]
                },
                "chat_threads_list:!room-b:example.com": b"not-json",
            }
        )
        logging_gateway = Mock()

        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            list_direct_rooms=AsyncMock(
                return_value=SimpleNamespace(
                    rooms={"@alice:example.com": ["!room-a:example.com"]},
                )
            ),
            joined_rooms=AsyncMock(
                return_value=SimpleNamespace(
                    rooms=["!room-a:example.com", "!room-b:example.com"]
                )
            ),
            room_get_state=AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        events=[
                            {
                                "type": "m.room.encryption",
                                "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                            },
                            {
                                "type": "m.room.name",
                                "content": {"name": "Room A"},
                            },
                        ]
                    ),
                    SimpleNamespace(
                        events=[
                            SimpleNamespace(
                                type="m.room.name",
                                content={"name": "Room B"},
                            )
                        ]
                    ),
                ]
            ),
            joined_members=AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        members=[
                            SimpleNamespace(user_id="@assistant:example.com"),
                            SimpleNamespace(user_id="@alice:example.com"),
                        ]
                    ),
                    SimpleNamespace(
                        members=[
                            SimpleNamespace(user_id="@assistant:example.com"),
                            SimpleNamespace(user_id="@bob:example.com"),
                        ]
                    ),
                ]
            ),
            room_leave=AsyncMock(),
            room_kick=AsyncMock(),
        )

        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=logging_gateway,
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_list_rooms",
                data={},
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.handler, "RoomManagementIPCExtension")
        self.assertEqual(
            response.response,
            {
                "response": {
                    "rooms": [
                        {
                            "room_id": "!room-a:example.com",
                            "members": ["@alice:example.com"],
                            "chat_threads": ["thread:1", "thread:2"],
                            "encrypted": "m.megolm.v1.aes-sha2",
                            "direct": True,
                            "room_name": "Room A",
                        },
                        {
                            "room_id": "!room-b:example.com",
                            "members": ["@bob:example.com"],
                            "chat_threads": [],
                            "direct": False,
                            "room_name": "Room B",
                        },
                    ]
                }
            },
        )
        logging_gateway.warning.assert_called_once()

    async def test_matrix_leave_all_rooms_kicks_members_and_cleans_threads(self) -> None:
        keyval_storage_gateway = _InMemoryKeyValStorageGateway(
            {
                "chat_threads_list:!room-a:example.com": {"threads": ["thread:a"]},
                "thread:a": b"payload",
            }
        )
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            joined_rooms=AsyncMock(
                return_value=SimpleNamespace(
                    rooms=["!room-a:example.com", "!room-b:example.com"]
                )
            ),
            joined_members=AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        members=[
                            SimpleNamespace(user_id="@assistant:example.com"),
                            SimpleNamespace(user_id="@alice:example.com"),
                        ]
                    ),
                    SimpleNamespace(
                        members=[SimpleNamespace(user_id="@assistant:example.com")]
                    ),
                ]
            ),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
        )
        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_leave_all_rooms",
                data={},
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.response, {"response": "OK"})
        matrix_client.room_kick.assert_awaited_once_with(
            "!room-a:example.com",
            "@alice:example.com",
        )
        matrix_client.room_leave.assert_has_awaits(
            [
                call("!room-a:example.com"),
                call("!room-b:example.com"),
            ]
        )
        self.assertIn("thread:a", keyval_storage_gateway.removed_keys)
        self.assertIn(
            "chat_threads_list:!room-a:example.com",
            keyval_storage_gateway.removed_keys,
        )

    async def test_matrix_leave_empty_rooms_only_leaves_empty_rooms(self) -> None:
        keyval_storage_gateway = _InMemoryKeyValStorageGateway(
            {
                "chat_threads_list:!room-a:example.com": {"threads": ["thread:a"]},
                "thread:a": b"payload",
            }
        )
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            joined_rooms=AsyncMock(
                return_value=SimpleNamespace(
                    rooms=["!room-a:example.com", "!room-b:example.com"]
                )
            ),
            joined_members=AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        members=[SimpleNamespace(user_id="@assistant:example.com")]
                    ),
                    SimpleNamespace(
                        members=[
                            SimpleNamespace(user_id="@assistant:example.com"),
                            SimpleNamespace(user_id="@bob:example.com"),
                        ]
                    ),
                ]
            ),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
        )
        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=keyval_storage_gateway,
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_leave_empty_rooms",
                data={},
            )
        )

        self.assertTrue(response.ok)
        self.assertEqual(response.response, {"response": "OK"})
        matrix_client.room_leave.assert_awaited_once_with("!room-a:example.com")
        matrix_client.room_kick.assert_not_called()
        self.assertIn(
            "chat_threads_list:!room-a:example.com",
            keyval_storage_gateway.removed_keys,
        )

    async def test_unknown_command_returns_not_found(self) -> None:
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            joined_rooms=AsyncMock(return_value=SimpleNamespace(rooms=[])),
            joined_members=AsyncMock(return_value=SimpleNamespace(members=[])),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
            room_get_state=AsyncMock(return_value=SimpleNamespace(events=[])),
        )
        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=_InMemoryKeyValStorageGateway(),
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="unknown_matrix_command",
                data={},
            )
        )

        self.assertFalse(response.ok)
        self.assertEqual(response.code, "not_found")
        self.assertEqual(response.error, "Unsupported IPC command.")

    async def test_constructor_fallback_and_helper_guard_paths(self) -> None:
        keyval_storage_gateway = _InMemoryKeyValStorageGateway()
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            joined_rooms=AsyncMock(return_value=SimpleNamespace(rooms="invalid")),
            joined_members=AsyncMock(return_value=SimpleNamespace(members=[])),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
            room_get_state=AsyncMock(return_value=SimpleNamespace(events=[])),
        )
        logging_gateway = Mock()

        with patch.object(
            room_ipc_ext_module.di,
            "container",
            SimpleNamespace(
                matrix_client=matrix_client,
                keyval_storage_gateway=keyval_storage_gateway,
                logging_gateway=logging_gateway,
            ),
        ):
            ext = RoomManagementIPCExtension()

        self.assertEqual(
            ext.ipc_commands,
            [
                "matrix_leave_all_rooms",
                "matrix_leave_empty_rooms",
                "matrix_list_rooms",
            ],
        )
        self.assertEqual(ext.platforms, ["matrix"])
        self.assertEqual(await ext._joined_room_ids(), [])  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            ext._collect_member_ids(SimpleNamespace(members="invalid")),
            [],
        )
        self.assertEqual(  # pylint: disable=protected-access
            ext._collect_member_ids(
                SimpleNamespace(
                    members=[
                        SimpleNamespace(user_id=123),
                        SimpleNamespace(user_id="@assistant:example.com"),
                        SimpleNamespace(user_id="@valid:example.com"),
                    ]
                )
            ),
            ["@valid:example.com"],
        )
        self.assertEqual(  # pylint: disable=protected-access
            ext._state_events(SimpleNamespace(events="invalid")),
            [],
        )
        self.assertIsNone(  # pylint: disable=protected-access
            ext._state_event_content(
                [{"type": "m.room.name", "content": "invalid"}],
                "m.room.name",
            )
        )

        self.assertEqual(  # pylint: disable=protected-access
            await ext._load_chat_thread_keys("!missing:example.com"),
            [],
        )

        keyval_storage_gateway._values["chat_threads_list:!empty:example.com"] = ""
        self.assertEqual(  # pylint: disable=protected-access
            await ext._load_chat_thread_keys("!empty:example.com"),
            [],
        )

        keyval_storage_gateway._values["chat_threads_list:!string:example.com"] = "bad"
        self.assertEqual(  # pylint: disable=protected-access
            await ext._load_chat_thread_keys("!string:example.com"),
            [],
        )

        keyval_storage_gateway._values["chat_threads_list:!invalid-type:example.com"] = 123
        self.assertEqual(  # pylint: disable=protected-access
            await ext._load_chat_thread_keys("!invalid-type:example.com"),
            [],
        )

        keyval_storage_gateway._values["chat_threads_list:!list:example.com"] = [
            "thread:1"
        ]
        self.assertEqual(  # pylint: disable=protected-access
            await ext._load_chat_thread_keys("!list:example.com"),
            [],
        )

        keyval_storage_gateway._values["chat_threads_list:!threads:example.com"] = {
            "threads": "thread:1"
        }
        self.assertEqual(  # pylint: disable=protected-access
            await ext._load_chat_thread_keys("!threads:example.com"),
            [],
        )

    async def test_matrix_leave_empty_rooms_skips_invalid_single_member_cases(
        self,
    ) -> None:
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            joined_rooms=AsyncMock(
                return_value=SimpleNamespace(
                    rooms=["!invalid-members:example.com", "!other-user:example.com"]
                )
            ),
            joined_members=AsyncMock(
                side_effect=[
                    SimpleNamespace(members="invalid"),
                    SimpleNamespace(members=[SimpleNamespace(user_id="@other:example.com")]),
                ]
            ),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
        )
        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=_InMemoryKeyValStorageGateway(),
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_leave_empty_rooms",
                data={},
            )
        )

        self.assertTrue(response.ok)
        matrix_client.room_leave.assert_not_called()

    async def test_matrix_list_rooms_ignores_non_string_state_fields(self) -> None:
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            list_direct_rooms=AsyncMock(
                return_value=SimpleNamespace(
                    rooms={"@alice:example.com": ["!room:example.com"]},
                )
            ),
            joined_rooms=AsyncMock(return_value=SimpleNamespace(rooms=["!room:example.com"])),
            room_get_state=AsyncMock(
                return_value=SimpleNamespace(
                    events=[
                        {
                            "type": "m.room.encryption",
                            "content": {"algorithm": 123},
                        },
                        {
                            "type": "m.room.name",
                            "content": {"name": 123},
                        },
                    ]
                )
            ),
            joined_members=AsyncMock(
                return_value=SimpleNamespace(
                    members=[
                        SimpleNamespace(user_id="@assistant:example.com"),
                        SimpleNamespace(user_id="@alice:example.com"),
                    ]
                )
            ),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
        )
        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=_InMemoryKeyValStorageGateway(),
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_list_rooms",
                data={},
            )
        )

        self.assertTrue(response.ok)
        room_payload = response.response["response"]["rooms"][0]
        self.assertEqual(room_payload["room_id"], "!room:example.com")
        self.assertEqual(room_payload["members"], ["@alice:example.com"])
        self.assertEqual(room_payload["chat_threads"], [])
        self.assertTrue(room_payload["direct"])
        self.assertNotIn("encrypted", room_payload)
        self.assertNotIn("room_name", room_payload)

    async def test_matrix_list_rooms_allows_missing_room_name_event(self) -> None:
        matrix_client = SimpleNamespace(
            user_id="@assistant:example.com",
            joined_rooms=AsyncMock(
                return_value=SimpleNamespace(rooms=["!room-no-name:example.com"])
            ),
            room_get_state=AsyncMock(
                return_value=SimpleNamespace(
                    events=[
                        {
                            "type": "m.room.encryption",
                            "content": {"algorithm": "m.megolm.v1.aes-sha2"},
                        }
                    ]
                )
            ),
            joined_members=AsyncMock(
                return_value=SimpleNamespace(
                    members=[
                        SimpleNamespace(user_id="@assistant:example.com"),
                        SimpleNamespace(user_id="@alice:example.com"),
                    ]
                )
            ),
            room_kick=AsyncMock(),
            room_leave=AsyncMock(),
        )
        ext = RoomManagementIPCExtension(
            matrix_client=matrix_client,
            keyval_storage_gateway=_InMemoryKeyValStorageGateway(),
            logging_gateway=Mock(),
        )

        response = await ext.process_ipc_command(
            IPCCommandRequest(
                platform="matrix",
                command="matrix_list_rooms",
                data={},
            )
        )

        self.assertTrue(response.ok)
        room_payload = response.response["response"]["rooms"][0]
        self.assertEqual(room_payload["room_id"], "!room-no-name:example.com")
        self.assertNotIn("room_name", room_payload)

    async def test_direct_room_ids_returns_empty_for_non_dict_payload(self) -> None:
        ext = RoomManagementIPCExtension(
            matrix_client=SimpleNamespace(
                list_direct_rooms=AsyncMock(return_value=SimpleNamespace(rooms=["!room:example.com"])),
            ),
            keyval_storage_gateway=_InMemoryKeyValStorageGateway(),
            logging_gateway=Mock(),
        )

        self.assertEqual(await ext._direct_room_ids(), set())  # pylint: disable=protected-access

    async def test_direct_room_ids_filters_non_list_and_invalid_room_ids(self) -> None:
        ext = RoomManagementIPCExtension(
            matrix_client=SimpleNamespace(
                list_direct_rooms=AsyncMock(
                    return_value=SimpleNamespace(
                        rooms={
                            "@alice:example.com": ["!room-a:example.com", "", 123],
                            "@bob:example.com": "!room-b:example.com",
                        }
                    )
                ),
            ),
            keyval_storage_gateway=_InMemoryKeyValStorageGateway(),
            logging_gateway=Mock(),
        )

        self.assertEqual(
            await ext._direct_room_ids(),  # pylint: disable=protected-access
            {"!room-a:example.com"},
        )
