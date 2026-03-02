"""Unit tests for matrix DefaultMatrixClient utility and branch behavior."""

from io import BytesIO
import asyncio
import contextlib
import json
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from nio import LocalProtocolError

from mugen.core.client import matrix as matrix_mod
from mugen.core.client.matrix import DefaultMatrixClient
from mugen.core.contract.service.ipc import IPCCommandRequest, IPCHandlerResult
from mugen.core.service.ipc import DefaultIPCService


class _DeviceStore(dict):
    def active_user_devices(self, user_id: str) -> list[SimpleNamespace]:
        devices = self.get(user_id, {})
        return [SimpleNamespace(device_id=device_id) for device_id in devices.keys()]


class _DeviceStoreNoGet:  # pylint: disable=too-few-public-methods
    def __init__(self, devices_by_user: dict[str, dict[str, object]]):
        self._devices_by_user = devices_by_user

    def __getitem__(self, user_id: str) -> dict[str, object]:
        return self._devices_by_user[user_id]

    def active_user_devices(self, user_id: str) -> list[SimpleNamespace]:
        devices = self._devices_by_user.get(user_id, {})
        return [SimpleNamespace(device_id=device_id) for device_id in devices.keys()]


class _FakeUploadResponse:  # pylint: disable=too-few-public-methods
    def __init__(self, content_uri: str = "mxc://example/media") -> None:
        self.content_uri = content_uri


class _FakeDiskDownloadResponse:  # pylint: disable=too-few-public-methods
    pass


class _FakeProfileGetResponse:  # pylint: disable=too-few-public-methods
    def __init__(self, displayname: str) -> None:
        self.displayname = displayname


class _FakeLoginResponse:  # pylint: disable=too-few-public-methods
    def __init__(self, access_token: str, device_id: str, user_id: str) -> None:
        self.access_token = access_token
        self.device_id = device_id
        self.user_id = user_id


class _FakeAsyncFileCtx:  # pylint: disable=too-few-public-methods
    def __init__(self, handle) -> None:
        self._handle = handle

    async def __aenter__(self):
        return self._handle

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeEncryptedAudio:  # pylint: disable=too-few-public-methods
    def __init__(self, sender: str = "@user:example.com") -> None:
        self.sender = sender
        self.source = {
            "content": {"file": {"url": "mxc://a"}, "info": {"mimetype": "a"}}
        }


class _FakeEncryptedFile:  # pylint: disable=too-few-public-methods
    def __init__(self, sender: str = "@user:example.com") -> None:
        self.sender = sender
        self.source = {
            "content": {"file": {"url": "mxc://f"}, "info": {"mimetype": "f"}}
        }


class _FakeEncryptedImage:  # pylint: disable=too-few-public-methods
    def __init__(self, sender: str = "@user:example.com") -> None:
        self.sender = sender
        self.source = {
            "content": {"file": {"url": "mxc://i"}, "info": {"mimetype": "i"}}
        }


class _FakeEncryptedVideo:  # pylint: disable=too-few-public-methods
    def __init__(self, sender: str = "@user:example.com") -> None:
        self.sender = sender
        self.source = {
            "content": {"file": {"url": "mxc://v"}, "info": {"mimetype": "v"}}
        }


class _FakeTextMessage:  # pylint: disable=too-few-public-methods
    def __init__(self, sender: str = "@user:example.com", body: str = "hello") -> None:
        self.sender = sender
        self.body = body
        self.event_id = "$event"


class _MatrixClientForTests(DefaultMatrixClient):
    @property
    def device_store(self):
        return self._test_device_store

    @device_store.setter
    def device_store(self, value) -> None:
        self._test_device_store = value


class _RecordingMatrixEventIPCExtension:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.events: list[dict] = []

    @property
    def platforms(self) -> list[str]:
        return ["matrix"]

    @property
    def ipc_commands(self) -> list[str]:
        return ["matrix_event"]

    def platform_supported(self, platform: str) -> bool:
        return platform in self.platforms

    async def process_ipc_command(
        self,
        request: IPCCommandRequest,
    ) -> IPCHandlerResult:
        data = request.data if isinstance(request.data, dict) else {}
        self.events.append(
            {
                "callback": data.get("callback"),
                "event_type": data.get("event_type"),
                "reason": data.get("reason"),
                "room_id": data.get("room_id"),
            }
        )
        return IPCHandlerResult(
            handler=type(self).__name__,
            response={"ok": True},
        )


class TestMugenClientMatrix(unittest.IsolatedAsyncioTestCase):
    """Tests focused on direct unit coverage for DefaultMatrixClient."""

    def test_init_wires_dependencies_and_callbacks(self) -> None:
        config = SimpleNamespace(
            basedir="/tmp",
            matrix=SimpleNamespace(
                homeserver="https://matrix.example.com",
                client=SimpleNamespace(user="@assistant:example.com"),
                storage=SimpleNamespace(olm=SimpleNamespace(path="olm")),
            ),
        )
        ipc_service = Mock()
        keyval_storage_gateway = Mock()
        logging_gateway = Mock()
        messaging_service = Mock()
        user_service = Mock()

        with (
            patch.object(
                matrix_mod.AsyncClient, "__init__", autospec=True, return_value=None
            ) as base_init,
            patch.object(
                DefaultMatrixClient, "add_event_callback", autospec=True
            ) as add_event_callback,
            patch.object(
                DefaultMatrixClient, "add_to_device_callback", autospec=True
            ) as add_to_device_callback,
            patch.object(
                DefaultMatrixClient, "add_response_callback", autospec=True
            ) as add_response_callback,
        ):
            client = DefaultMatrixClient(
                config=config,
                ipc_service=ipc_service,
                keyval_storage_gateway=keyval_storage_gateway,
                logging_gateway=logging_gateway,
                messaging_service=messaging_service,
                user_service=user_service,
            )

        base_init.assert_called_once()
        self.assertEqual(
            base_init.call_args.kwargs["homeserver"],
            "https://matrix.example.com",
        )
        self.assertEqual(
            base_init.call_args.kwargs["user"],
            "@assistant:example.com",
        )
        self.assertEqual(
            base_init.call_args.kwargs["store_path"],
            "/tmp/olm",
        )
        self.assertIs(
            client._ipc_service, ipc_service
        )  # pylint: disable=protected-access
        self.assertIs(  # pylint: disable=protected-access
            client._keyval_storage_gateway, keyval_storage_gateway
        )
        self.assertIs(  # pylint: disable=protected-access
            client._logging_gateway, logging_gateway
        )
        self.assertIs(  # pylint: disable=protected-access
            client._messaging_service, messaging_service
        )
        self.assertIs(
            client._user_service, user_service
        )  # pylint: disable=protected-access

        self.assertEqual(add_event_callback.call_count, 7)
        self.assertEqual(add_to_device_callback.call_count, 3)
        add_response_callback.assert_called_once_with(
            client,
            client._cb_sync_response,  # pylint: disable=protected-access
            matrix_mod.SyncResponse,
        )

        expected_event_types = [
            matrix_mod.InviteAliasEvent,
            matrix_mod.InviteMemberEvent,
            matrix_mod.InviteNameEvent,
            matrix_mod.MegolmEvent,
            matrix_mod.RoomCreateEvent,
            matrix_mod.RoomMemberEvent,
            matrix_mod.RoomMessage,
        ]
        event_types = [call.args[2] for call in add_event_callback.call_args_list]
        self.assertEqual(event_types, expected_event_types)

        expected_to_device_event_types = [
            matrix_mod.KeyVerificationEvent,
            matrix_mod.RoomKeyEvent,
            matrix_mod.RoomKeyRequest,
        ]
        to_device_event_types = [
            call.args[2] for call in add_to_device_callback.call_args_list
        ]
        self.assertEqual(to_device_event_types, expected_to_device_event_types)

    def test_matrix_secrets_encryption_required_normalizes_platform_names(self) -> None:
        client = object.__new__(DefaultMatrixClient)
        client._config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="development",
                platforms=[" Matrix ", "web"],
            )
        )

        self.assertTrue(
            client._matrix_secrets_encryption_required()  # pylint: disable=protected-access
        )

    def test_getattr_raises_when_vendor_client_is_unset(self) -> None:
        client = object.__new__(DefaultMatrixClient)
        with self.assertRaises(AttributeError):
            _ = client.non_existent_attr

    def test_init_requires_encryption_key_for_matrix_enabled_platform(self) -> None:
        config = SimpleNamespace(
            basedir="/tmp",
            mugen=SimpleNamespace(
                environment="development",
                platforms=[" Matrix "],
            ),
            matrix=SimpleNamespace(
                homeserver="https://matrix.example.com",
                client=SimpleNamespace(user="@assistant:example.com"),
                storage=SimpleNamespace(olm=SimpleNamespace(path="olm")),
            ),
            security=SimpleNamespace(
                secrets=SimpleNamespace(
                    encryption_key=None,
                )
            ),
        )

        with (
            patch.object(
                matrix_mod.AsyncClient,
                "__init__",
                autospec=True,
                return_value=None,
            ),
            patch.object(DefaultMatrixClient, "add_event_callback", autospec=True),
            patch.object(DefaultMatrixClient, "add_to_device_callback", autospec=True),
            patch.object(DefaultMatrixClient, "add_response_callback", autospec=True),
            self.assertRaises(RuntimeError),
        ):
            DefaultMatrixClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )

    def _client(self) -> DefaultMatrixClient:
        client = object.__new__(_MatrixClientForTests)
        client._config = SimpleNamespace(
            basedir="/tmp",
            matrix=SimpleNamespace(
                homeserver="https://matrix.example.com",
                client=SimpleNamespace(
                    user="@assistant:example.com",
                    password="pw",
                    device="device",
                ),
                storage=SimpleNamespace(olm=SimpleNamespace(path="olm")),
                domains=SimpleNamespace(
                    allowed=["example.com"],
                    denied=[],
                ),
                beta=SimpleNamespace(users=["@beta:example.com"]),
                invites=SimpleNamespace(direct_only=True),
                security=SimpleNamespace(
                    device_trust=SimpleNamespace(
                        mode="strict_known",
                        allowlist=[],
                    )
                ),
            ),
            mugen=SimpleNamespace(beta=SimpleNamespace(active=False)),
        )
        client._logging_gateway = Mock()
        client._keyval_storage_gateway = Mock()
        client._vendor_client = SimpleNamespace(
            synced=asyncio.Event(),
            sync_forever=AsyncMock(),
            get_profile=AsyncMock(),
            set_displayname=AsyncMock(),
            add_event_callback=Mock(),
            add_to_device_callback=Mock(),
            add_response_callback=Mock(),
        )
        client.synced = client._vendor_client.synced
        client._keyval_data: dict[str, str | bytes] = {}

        def _sync_get(key: str, decode: bool = True):  # noqa: ARG001
            return client._keyval_data.get(key)

        def _sync_put(key: str, value: str | bytes):
            client._keyval_data[key] = value

        def _sync_remove(key: str):
            return client._keyval_data.pop(key, None)

        async def _get_text(key: str, namespace: str | None = None):  # noqa: ARG001
            value = client._keyval_data.get(key)
            if value is None:
                return None
            if isinstance(value, bytes):
                return value.decode("utf-8")
            return str(value)

        async def _put_text(
            key: str,
            value: str,
            namespace: str | None = None,  # noqa: ARG001
            expected_row_version: int | None = None,  # noqa: ARG001
            ttl_seconds: float | None = None,  # noqa: ARG001
        ):
            client._keyval_data[key] = value
            return None

        async def _put_json(
            key: str,
            value,
            namespace: str | None = None,  # noqa: ARG001
            expected_row_version: int | None = None,  # noqa: ARG001
            ttl_seconds: float | None = None,  # noqa: ARG001
        ):
            client._keyval_data[key] = json.dumps(
                value, ensure_ascii=True, separators=(",", ":")
            )
            return None

        client._keyval_storage_gateway.get = Mock(side_effect=_sync_get)
        client._keyval_storage_gateway.put = Mock(side_effect=_sync_put)
        client._keyval_storage_gateway.remove = Mock(side_effect=_sync_remove)
        client._keyval_storage_gateway.has_key = Mock(
            side_effect=lambda key: key in client._keyval_data
        )
        client._keyval_storage_gateway.keys = Mock(
            side_effect=lambda: list(client._keyval_data.keys())
        )
        client._keyval_storage_gateway.get_text = AsyncMock(side_effect=_get_text)
        client._keyval_storage_gateway.put_text = AsyncMock(side_effect=_put_text)
        client._keyval_storage_gateway.put_json = AsyncMock(side_effect=_put_json)
        client._messaging_service = Mock()
        client._user_service = SimpleNamespace(
            add_known_user=AsyncMock(),
            get_known_users_list=AsyncMock(return_value={}),
            get_user_display_name=AsyncMock(return_value=""),
            save_known_users_list=AsyncMock(),
        )
        client._ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock())
        client._direct_room_ids = set()
        client._matrix_ipc_queue_size = 256
        client._matrix_ipc_queue = None
        client._matrix_ipc_worker_task = None
        client._matrix_ipc_worker_stop = asyncio.Event()
        client._sync_token = None
        client.access_token = "access-token"
        client.user_id = "@assistant:example.com"
        client.login = AsyncMock()
        client.load_store = Mock()
        client.list_direct_rooms = AsyncMock(return_value=SimpleNamespace(rooms={}))
        client._send = AsyncMock(return_value=matrix_mod.EmptyResponse())
        client.get_profile = AsyncMock()
        client.room_leave = AsyncMock()
        client.join = AsyncMock()
        client.room_put_state = AsyncMock()
        client.room_get_state = AsyncMock()
        client.room_read_markers = AsyncMock()
        client.room_typing = AsyncMock()
        client.room_send = AsyncMock()
        client.upload = AsyncMock()
        client.download = AsyncMock()
        client.verify_device = Mock()
        client.device_store = _DeviceStore()
        client.client_session = SimpleNamespace(close=AsyncMock())
        return client

    async def test_get_profile_wraps_asyncclient_response(self) -> None:
        client = self._client()
        response = SimpleNamespace(
            displayname="Assistant",
            avatar_url="mxc://example/avatar",
        )
        client._vendor_client.get_profile = AsyncMock(return_value=response)  # pylint: disable=protected-access
        profile = await DefaultMatrixClient.get_profile(client, user_id="@u:example.com")

        client._vendor_client.get_profile.assert_awaited_once_with(  # pylint: disable=protected-access
            user_id="@u:example.com"
        )
        self.assertEqual(profile.user_id, "@u:example.com")
        self.assertEqual(profile.displayname, "Assistant")
        self.assertEqual(profile.avatar_url, "mxc://example/avatar")
        self.assertEqual(
            profile.metadata.get("vendor_response_type"),
            type(response).__name__,
        )

    async def test_set_displayname_delegates_to_asyncclient(self) -> None:
        client = self._client()
        client._vendor_client.set_displayname = AsyncMock(return_value=object())  # pylint: disable=protected-access
        await DefaultMatrixClient.set_displayname(client, "New Name")

        client._vendor_client.set_displayname.assert_awaited_once_with(  # pylint: disable=protected-access
            "New Name"
        )

    async def test_sync_forever_delegates_to_vendor_client(self) -> None:
        client = self._client()
        client._vendor_client.sync_forever = AsyncMock(return_value=None)  # pylint: disable=protected-access

        await DefaultMatrixClient.sync_forever(
            client,
            since="s1",
            timeout=500,
            full_state=False,
            set_presence="offline",
        )

        client._vendor_client.sync_forever.assert_awaited_once_with(  # pylint: disable=protected-access
            since="s1",
            timeout=500,
            full_state=False,
            set_presence="offline",
        )

    async def test_callback_registration_wrappers_delegate_to_vendor_client(self) -> None:
        client = self._client()
        callback = Mock()
        event_type = object()
        response_type = object()

        client.add_event_callback(callback, event_type)
        client.add_to_device_callback(callback, event_type)
        client.add_response_callback(callback, response_type)

        client._vendor_client.add_event_callback.assert_called_once_with(  # pylint: disable=protected-access
            callback, event_type
        )
        client._vendor_client.add_to_device_callback.assert_called_once_with(  # pylint: disable=protected-access
            callback, event_type
        )
        client._vendor_client.add_response_callback.assert_called_once_with(  # pylint: disable=protected-access
            callback, response_type
        )

    async def test_vendor_property_and_method_wrappers_delegate_explicitly(self) -> None:
        client = self._client()
        client._vendor_client = SimpleNamespace(  # pylint: disable=protected-access
            access_token="tok-1",
            device_id="dev-1",
            user_id="@assistant:example.com",
            client_session=SimpleNamespace(close=AsyncMock()),
            olm=SimpleNamespace(),
            verify_device=Mock(),
            login=AsyncMock(return_value={"ok": True}),
            load_store=Mock(),
            join=AsyncMock(return_value={"joined": True}),
            list_direct_rooms=AsyncMock(return_value={"rooms": {}}),
            joined_rooms=AsyncMock(return_value={"rooms": []}),
            joined_members=AsyncMock(return_value={"members": []}),
            room_get_state=AsyncMock(return_value={"events": []}),
            room_kick=AsyncMock(return_value={"kicked": True}),
            room_leave=AsyncMock(return_value={"left": True}),
            room_send=AsyncMock(return_value={"sent": True}),
            room_typing=AsyncMock(return_value={"typing": True}),
            room_read_markers=AsyncMock(return_value={"markers": True}),
            upload=AsyncMock(return_value={"uploaded": True}),
            download=AsyncMock(return_value={"downloaded": True}),
            _send=AsyncMock(return_value={"raw": True}),
        )

        self.assertEqual(client.current_user_id, "@assistant:example.com")
        client.user_id = None
        self.assertEqual(client.current_user_id, "")
        self.assertEqual(client.device_store, {})
        client.device_store = {"ok": True}
        self.assertEqual(client.device_store, {"ok": True})

        client.olm = SimpleNamespace(account=SimpleNamespace(identity_keys={}))
        self.assertIsNotNone(client.olm)
        DefaultMatrixClient.verify_device(client, "dev")
        client._vendor_client.verify_device.assert_called_once_with("dev")  # pylint: disable=protected-access

        self.assertEqual(
            await DefaultMatrixClient.login(client, "pw", "device"),
            {"ok": True},
        )
        DefaultMatrixClient.load_store(client)
        client._vendor_client.load_store.assert_called_once_with()  # pylint: disable=protected-access
        self.assertEqual(await DefaultMatrixClient.join(client, "!room:test"), {"joined": True})
        self.assertEqual(
            await DefaultMatrixClient.list_direct_rooms(client),
            {"rooms": {}},
        )
        self.assertEqual(await DefaultMatrixClient.joined_rooms(client), {"rooms": []})
        self.assertEqual(
            await DefaultMatrixClient.joined_members(client, "!room:test"),
            {"members": []},
        )
        self.assertEqual(
            await DefaultMatrixClient.room_get_state(client, "!room:test"),
            {"events": []},
        )
        self.assertEqual(
            await DefaultMatrixClient.room_kick(client, "!room:test", "@u:example.com"),
            {"kicked": True},
        )
        self.assertEqual(
            await DefaultMatrixClient.room_leave(client, "!room:test"),
            {"left": True},
        )
        self.assertEqual(
            await DefaultMatrixClient.room_send(
                client,
                "!room:test",
                "m.room.message",
                {"body": "hi"},
            ),
            {"sent": True},
        )
        self.assertEqual(
            await DefaultMatrixClient.room_typing(client, "!room:test", True),
            {"typing": True},
        )
        self.assertEqual(
            await DefaultMatrixClient.room_read_markers(
                client,
                "!room:test",
                "$event",
                "$event",
            ),
            {"markers": True},
        )
        self.assertEqual(await DefaultMatrixClient.upload(client, b"bin"), {"uploaded": True})
        self.assertEqual(
            await DefaultMatrixClient.download(client, "mxc://example/file"),
            {"downloaded": True},
        )
        self.assertEqual(
            await DefaultMatrixClient._send(client, "GET", "/path"),  # pylint: disable=protected-access
            {"raw": True},
        )

        del client.client_session
        del client.client_session

    async def test_matrix_admin_helpers_normalize_vendor_payloads(self) -> None:
        client = self._client()
        client._vendor_client.joined_rooms = AsyncMock(  # pylint: disable=protected-access
            side_effect=[
                SimpleNamespace(rooms=["!a:test", "", None, 1]),
                SimpleNamespace(rooms=None),
            ]
        )
        client._vendor_client.joined_members = AsyncMock(  # pylint: disable=protected-access
            side_effect=[
                SimpleNamespace(
                    members=[
                        SimpleNamespace(user_id="@u1:test"),
                        SimpleNamespace(user_id=""),
                        SimpleNamespace(),
                    ]
                ),
                SimpleNamespace(members=None),
            ]
        )
        client._vendor_client.room_get_state = AsyncMock(  # pylint: disable=protected-access
            side_effect=[
                SimpleNamespace(
                    events=[
                        {"type": "m.room.create", "content": {"creator": "@u:test"}},
                        SimpleNamespace(type="m.room.name", content={"name": "Demo"}),
                    ]
                ),
                SimpleNamespace(events=None),
            ]
        )
        client.room_get_state = AsyncMock(
            side_effect=[
                SimpleNamespace(
                    events=[
                        {"type": "m.room.create", "content": {"creator": "@u:test"}},
                        SimpleNamespace(type="m.room.name", content={"name": "Demo"}),
                    ]
                ),
                SimpleNamespace(events=None),
            ]
        )
        client.list_direct_rooms = AsyncMock(
            side_effect=[
                SimpleNamespace(
                    rooms={
                        "@u:test": ["!a:test", "", None],
                        "@v:test": ["!b:test"],
                        "@w:test": "bad",
                    }
                ),
                SimpleNamespace(rooms=None),
            ]
        )

        self.assertEqual(await client.joined_room_ids(), ["!a:test"])
        self.assertEqual(await client.joined_room_ids(), [])
        self.assertEqual(await client.joined_member_ids("!room:test"), ["@u1:test"])
        self.assertEqual(await client.joined_member_ids("!room:test"), [])
        self.assertEqual(
            await client.room_state_events("!room:test"),
            [
                {"type": "m.room.create", "content": {"creator": "@u:test"}},
                {"type": "m.room.name", "content": {"name": "Demo"}},
            ],
        )
        self.assertEqual(await client.room_state_events("!room:test"), [])
        self.assertEqual(await client.direct_room_ids(), {"!a:test", "!b:test"})
        self.assertEqual(await client.direct_room_ids(), set())

        client.olm = SimpleNamespace(account=SimpleNamespace(identity_keys={"ed25519": "k1"}))
        self.assertEqual(client.device_ed25519_key(), "k1")
        client.olm = SimpleNamespace(account=SimpleNamespace(identity_keys={"ed25519": ""}))
        self.assertEqual(client.device_ed25519_key(), "")
        client.olm = SimpleNamespace(account=SimpleNamespace(identity_keys=None))
        self.assertEqual(client.device_ed25519_key(), "")

    async def test_send_wrapper_raises_when_vendor_send_missing(self) -> None:
        client = self._client()
        client._vendor_client = SimpleNamespace()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "does not expose _send"):
            await DefaultMatrixClient._send(client, "GET", "/path")  # pylint: disable=protected-access

    def test_device_store_property_uses_vendor_store_on_base_client(self) -> None:
        client = object.__new__(DefaultMatrixClient)
        client._vendor_client = SimpleNamespace()  # pylint: disable=protected-access

        self.assertEqual(DefaultMatrixClient.device_store.fget(client), {})

        DefaultMatrixClient.device_store.fset(client, {"@u:test": {"DEV": object()}})
        self.assertIn("@u:test", DefaultMatrixClient.device_store.fget(client))

    async def test_build_matrix_event_hook_payload_serializes_and_sanitizes(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        event = SimpleNamespace(
            sender="@user:example.com",
            content={"safe": "value", "bad": {1, 2, 3}},
            source={"safe": True},
            event_id=" $event ",
            state_key=" ",
            origin_server_ts="bad",
        )

        payload = client._build_matrix_event_hook_payload(  # pylint: disable=protected-access
            callback_name="_cb_tag_event",
            event=event,
            room=room,
            reason="unit-test",
        )

        self.assertEqual(payload["callback"], "_cb_tag_event")
        self.assertEqual(payload["event_type"], "SimpleNamespace")
        self.assertEqual(payload["room_id"], "!room:test")
        self.assertEqual(payload["sender"], "@user:example.com")
        self.assertIsNone(payload["content"])
        self.assertEqual(payload["source"], {"safe": True})
        self.assertEqual(payload["event_id"], "$event")
        self.assertIsNone(payload["state_key"])
        self.assertIsNone(payload["origin_server_ts"])

    async def test_normalize_event_dict_rejects_non_dict_roundtrip_value(self) -> None:
        client = self._client()
        with patch("mugen.core.client.matrix.json.loads", return_value=[]):
            self.assertIsNone(
                client._normalize_event_dict({"safe": "value"})  # pylint: disable=protected-access
            )

    async def test_coerce_optional_int_accepts_valid_values(self) -> None:
        client = self._client()
        self.assertEqual(
            client._coerce_optional_int("123"),  # pylint: disable=protected-access
            123,
        )

    def test_init_requires_secret_encryption_key_when_matrix_enabled(self) -> None:
        config = SimpleNamespace(
            basedir="/tmp",
            mugen=SimpleNamespace(environment="development", platforms=["matrix"]),
            matrix=SimpleNamespace(
                homeserver="https://matrix.example.com",
                client=SimpleNamespace(user="@assistant:example.com"),
                storage=SimpleNamespace(olm=SimpleNamespace(path="olm")),
            ),
        )

        with (
            patch.object(
                matrix_mod.AsyncClient, "__init__", autospec=True, return_value=None
            ),
            patch.object(DefaultMatrixClient, "add_event_callback", autospec=True),
            patch.object(DefaultMatrixClient, "add_to_device_callback", autospec=True),
            patch.object(DefaultMatrixClient, "add_response_callback", autospec=True),
            self.assertRaises(RuntimeError),
        ):
            DefaultMatrixClient(
                config=config,
                ipc_service=Mock(),
                keyval_storage_gateway=Mock(),
                logging_gateway=Mock(),
                messaging_service=Mock(),
                user_service=Mock(),
            )

    def test_secret_encoding_and_decoding_paths(self) -> None:
        client = self._client()
        with self.assertRaisesRegex(RuntimeError, "Cannot persist token"):
            client._encode_secret_value(  # pylint: disable=protected-access
                "access-token",
                field_name="token",
            )
        client._config.security = SimpleNamespace(
            secrets=SimpleNamespace(encryption_key="test-secret")
        )
        client._secret_cipher = client._build_secret_cipher()  # pylint: disable=protected-access

        encoded = client._encode_secret_value(  # pylint: disable=protected-access
            "access-token",
            field_name="token",
        )
        self.assertTrue(encoded.startswith(client._encrypted_secret_prefix))  # pylint: disable=protected-access
        self.assertEqual(
            client._decode_secret_value(encoded, field_name="token"),  # pylint: disable=protected-access
            "access-token",
        )

        with self.assertRaises(RuntimeError):
            client._encode_secret_value(1, field_name="token")  # pylint: disable=protected-access

        self.assertIsNone(
            client._decode_secret_value(1, field_name="token")  # pylint: disable=protected-access
        )

        with self.assertRaisesRegex(RuntimeError, "must be encrypted"):
            client._decode_secret_value(  # pylint: disable=protected-access
                "plaintext-token",
                field_name="token",
            )

    def test_secret_decoding_requires_valid_cipher_and_payload(self) -> None:
        client = self._client()
        encrypted_value = f"{client._encrypted_secret_prefix}payload"  # pylint: disable=protected-access

        client._secret_cipher = None  # pylint: disable=protected-access
        with self.assertRaises(RuntimeError):
            client._decode_secret_value(  # pylint: disable=protected-access
                encrypted_value,
                field_name="token",
            )

        client._config.security = SimpleNamespace(
            secrets=SimpleNamespace(encryption_key="test-secret")
        )
        client._secret_cipher = client._build_secret_cipher()  # pylint: disable=protected-access
        with self.assertRaises(RuntimeError):
            client._decode_secret_value(  # pylint: disable=protected-access
                encrypted_value,
                field_name="token",
            )

    async def test_matrix_ipc_queue_size_resolution_paths(self) -> None:
        client = self._client()
        client._config.matrix.ipc = SimpleNamespace(queue_size="invalid")
        self.assertEqual(
            client._resolve_matrix_ipc_queue_size(),  # pylint: disable=protected-access
            256,
        )
        client._config.matrix.ipc = SimpleNamespace(queue_size=0)
        self.assertEqual(
            client._resolve_matrix_ipc_queue_size(),  # pylint: disable=protected-access
            256,
        )

    async def test_start_matrix_ipc_worker_guards(self) -> None:
        client = self._client()
        client._ipc_service = None
        client._start_matrix_ipc_worker()  # pylint: disable=protected-access
        self.assertIsNone(client._matrix_ipc_worker_task)

        client = self._client()

        async def _never() -> None:
            await asyncio.sleep(60)

        existing_task = asyncio.create_task(_never())
        client._matrix_ipc_worker_task = existing_task
        try:
            client._start_matrix_ipc_worker()  # pylint: disable=protected-access
            self.assertIs(client._matrix_ipc_worker_task, existing_task)
        finally:
            existing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await existing_task

    async def test_stop_matrix_ipc_worker_cancels_running_task(self) -> None:
        client = self._client()
        client._matrix_ipc_queue = asyncio.Queue()

        async def _never() -> None:
            await asyncio.sleep(60)

        task = asyncio.create_task(_never())
        client._matrix_ipc_worker_task = task
        await client._stop_matrix_ipc_worker()  # pylint: disable=protected-access
        self.assertTrue(task.cancelled())
        self.assertIsNone(client._matrix_ipc_queue)
        self.assertIsNone(client._matrix_ipc_worker_task)

    async def test_dispatch_matrix_ipc_request_guard_paths(self) -> None:
        client = self._client()
        payload = IPCCommandRequest(platform="matrix", command="matrix_event", data={})

        client._ipc_service = None
        await client._dispatch_matrix_ipc_request(payload)  # pylint: disable=protected-access

        client._ipc_service = SimpleNamespace(handle_ipc_request=None)
        await client._dispatch_matrix_ipc_request(payload)  # pylint: disable=protected-access

        non_awaitable_handler = Mock(return_value=None)
        client._ipc_service = SimpleNamespace(handle_ipc_request=non_awaitable_handler)
        await client._dispatch_matrix_ipc_request(payload)  # pylint: disable=protected-access
        non_awaitable_handler.assert_called_once_with(payload)

    async def test_matrix_ipc_worker_loop_handles_empty_queue_and_errors(self) -> None:
        client = self._client()

        async def _sleep_and_stop(_delay: float) -> None:
            client._matrix_ipc_worker_stop.set()  # pylint: disable=protected-access

        client._matrix_ipc_queue = None
        with patch("mugen.core.client.matrix.asyncio.sleep", new=_sleep_and_stop):
            await client._matrix_ipc_worker_loop()  # pylint: disable=protected-access

        client = self._client()
        client._matrix_ipc_queue = asyncio.Queue()

        async def _wait_for_timeout(_awaitable, timeout):
            _ = timeout
            _awaitable.close()
            client._matrix_ipc_worker_stop.set()  # pylint: disable=protected-access
            raise asyncio.TimeoutError()

        with patch("mugen.core.client.matrix.asyncio.wait_for", new=_wait_for_timeout):
            await client._matrix_ipc_worker_loop()  # pylint: disable=protected-access

        client = self._client()
        client._matrix_ipc_queue = asyncio.Queue()
        await client._matrix_ipc_queue.put(
            IPCCommandRequest(platform="matrix", command="matrix_event", data={})
        )

        async def _raise_dispatch(_payload):
            client._matrix_ipc_worker_stop.set()  # pylint: disable=protected-access
            raise RuntimeError("boom")

        with patch.object(
            client,
            "_dispatch_matrix_ipc_request",
            new=_raise_dispatch,
        ):
            await client._matrix_ipc_worker_loop()  # pylint: disable=protected-access
        self.assertTrue(client._logging_gateway.warning.called)

    async def test_dispatch_matrix_event_hook_queue_full_drops_new(self) -> None:
        client = self._client()
        client._start_matrix_ipc_worker = Mock()
        client._matrix_ipc_queue = asyncio.Queue(maxsize=1)
        client._matrix_ipc_queue.put_nowait(
            IPCCommandRequest(platform="matrix", command="matrix_event", data={})
        )
        client._dispatch_matrix_ipc_request = AsyncMock()  # pylint: disable=protected-access

        await client._dispatch_matrix_event_hook(  # pylint: disable=protected-access
            callback_name="_cb_tag_event",
            event=SimpleNamespace(),
        )
        self.assertEqual(
            client._matrix_metrics["matrix.ipc.dispatch.queue_full_drop_new"],  # pylint: disable=protected-access
            1,
        )
        client._dispatch_matrix_ipc_request.assert_not_awaited()  # pylint: disable=protected-access
        self.assertTrue(client._logging_gateway.warning.called)

    async def test_dispatch_matrix_event_hook_no_queue_drops_new(self) -> None:
        client = self._client()
        client._start_matrix_ipc_worker = Mock()
        client._matrix_ipc_queue = None
        client._dispatch_matrix_ipc_request = AsyncMock()  # pylint: disable=protected-access
        await client._dispatch_matrix_event_hook(  # pylint: disable=protected-access
            callback_name="_cb_tag_event",
            event=SimpleNamespace(),
        )

        self.assertEqual(
            client._matrix_metrics["matrix.ipc.dispatch.queue_unavailable_drop_new"],  # pylint: disable=protected-access
            1,
        )
        client._dispatch_matrix_ipc_request.assert_not_awaited()  # pylint: disable=protected-access

    async def test_aenter_uses_saved_credentials_when_access_token_exists(self) -> None:
        client = self._client()
        client._ensure_credential_keys_initialized()  # pylint: disable=protected-access
        client._config.security = SimpleNamespace(
            secrets=SimpleNamespace(encryption_key="test-secret")
        )
        client._secret_cipher = client._build_secret_cipher()  # pylint: disable=protected-access

        values = {
            client._client_access_token_key: client._encode_secret_value(  # pylint: disable=protected-access
                "tok",
                field_name="client_access_token",
            ),
            client._client_device_id_key: client._encode_secret_value(  # pylint: disable=protected-access
                "dev",
                field_name="client_device_id",
            ),
            client._client_user_id_key: client._encode_secret_value(  # pylint: disable=protected-access
                "@assistant:example.com",
                field_name="client_user_id",
            ),
        }
        client._keyval_storage_gateway.get_text = AsyncMock(
            side_effect=lambda key, *_: values.get(key)
        )

        result = await client.__aenter__()

        self.assertIs(result, client)
        self.assertEqual(client.access_token, "tok")
        self.assertEqual(client.device_id, "dev")
        self.assertEqual(client.user_id, "@assistant:example.com")
        client.load_store.assert_called_once_with()

    async def test_aenter_password_login_success_saves_credentials(self) -> None:
        client = self._client()
        client._config.security = SimpleNamespace(
            secrets=SimpleNamespace(encryption_key="test-secret")
        )
        client._secret_cipher = client._build_secret_cipher()  # pylint: disable=protected-access
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)
        client.login = AsyncMock(
            return_value=_FakeLoginResponse("access", "device-1", "@user:example.com")
        )

        with patch.object(matrix_mod, "LoginResponse", _FakeLoginResponse):
            result = await client.__aenter__()

        self.assertIs(result, client)
        self.assertEqual(client._keyval_storage_gateway.put_text.await_count, 3)
        client.load_store.assert_called_once_with()

    async def test_aenter_password_login_without_cipher_raises(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)
        client.login = AsyncMock(
            return_value=_FakeLoginResponse("access", "device-1", "@user:example.com")
        )

        with (
            patch.object(matrix_mod, "LoginResponse", _FakeLoginResponse),
            self.assertRaisesRegex(RuntimeError, "Cannot persist client_access_token"),
        ):
            await client.__aenter__()

        client._keyval_storage_gateway.put_text.assert_not_awaited()

    async def test_aenter_password_login_failure_raises_runtime_error(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)
        client.login = AsyncMock(return_value=object())

        with (
            patch.object(matrix_mod, "LoginResponse", _FakeLoginResponse),
            self.assertRaisesRegex(RuntimeError, "Matrix password login failed"),
        ):
            await client.__aenter__()

    async def test_aenter_failure_triggers_close_cleanup(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value="plaintext-token")

        with self.assertRaisesRegex(RuntimeError, "must be encrypted"):
            await client.__aenter__()

        client.client_session.close.assert_awaited_once_with()
        self.assertIsNone(client._matrix_ipc_worker_task)  # pylint: disable=protected-access

    async def test_aexit_closes_client_session_and_handles_missing_session(
        self,
    ) -> None:
        client = self._client()
        await client.__aexit__(None, None, None)
        client.client_session.close.assert_awaited_once_with()

        del client.client_session
        await client.__aexit__(None, None, None)

    async def test_close_is_idempotent_and_skips_closed_session(self) -> None:
        client = self._client()
        await client.close()
        client.client_session.close.assert_awaited_once_with()

        closed_session = SimpleNamespace(close=AsyncMock(), closed=True)
        client.client_session = closed_session
        await client.close()
        closed_session.close.assert_not_awaited()

        del client.client_session
        await client.close()

    async def test_close_handles_session_without_close_attribute(self) -> None:
        client = self._client()
        client.client_session = object()
        await client.close()

    async def test_sync_token_property_reads_storage(self) -> None:
        client = self._client()
        client._sync_token = "next-batch"  # pylint: disable=protected-access
        self.assertEqual(client.sync_token, "next-batch")

    async def test_cleanup_and_trust_known_user_devices_list(self) -> None:
        client = self._client()
        known_devices = {"@user:example.com": ["DEV-1"]}
        client._keyval_storage_gateway.get_text = AsyncMock(
            return_value=json.dumps(known_devices),
        )
        client.device_store = _DeviceStore(
            {
                "@user:example.com": {
                    "DEV-1": object(),
                    "DEV-2": object(),
                }
            }
        )

        await client.cleanup_known_user_devices_list()

        persisted = client._keyval_storage_gateway.put_json.await_args.args[1]
        self.assertEqual(persisted["@user:example.com"], ["DEV-1", "DEV-2"])

        client.verify_device = Mock()
        await client.trust_known_user_devices()
        self.assertEqual(client.verify_device.call_count, 1)

    async def test_cleanup_and_trust_known_user_devices_no_stored_key(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)

        await client.cleanup_known_user_devices_list()
        await client.trust_known_user_devices()

        client._keyval_storage_gateway.put_json.assert_not_awaited()
        client.verify_device.assert_not_called()

    async def test_known_devices_invalid_payload_is_ignored(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value="{")

        await client.cleanup_known_user_devices_list()
        await client.trust_known_user_devices()

        client._keyval_storage_gateway.put_json.assert_not_awaited()
        client.verify_device.assert_not_called()
        self.assertGreaterEqual(client._logging_gateway.warning.call_count, 1)

    async def test_load_known_devices_handles_bytes_type_mismatch_and_value_filtering(
        self,
    ) -> None:
        client = self._client()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)
        self.assertEqual(
            await client._load_known_devices(), {}
        )  # pylint: disable=protected-access

        client._keyval_storage_gateway.get_text = AsyncMock(
            return_value=json.dumps(["not-a-dict"])
        )
        self.assertEqual(
            await client._load_known_devices(), {}
        )  # pylint: disable=protected-access

        client._keyval_storage_gateway.get_text = AsyncMock(
            return_value=json.dumps(
                {
                    "@user:example.com": "DEV-1",
                    "@other:example.com": ["DEV-2", 3],
                }
            )
        )
        self.assertEqual(
            await client._load_known_devices(),  # pylint: disable=protected-access
            {"@other:example.com": ["DEV-2", "3"]},
        )

    async def test_verify_user_devices_handles_new_and_already_known_devices(
        self,
    ) -> None:
        client = self._client()
        client._config.matrix.security.device_trust.mode = "permissive"
        client.device_store = _DeviceStore(
            {"@user:example.com": {"DEV-1": object(), "DEV-2": object()}}
        )
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)

        await client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 2)
        self.assertEqual(client._keyval_storage_gateway.put_json.await_count, 2)

        known = {"@user:example.com": ["DEV-1", "DEV-2"]}
        client.verify_device.reset_mock()
        client._keyval_storage_gateway.put_json.reset_mock()
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=json.dumps(known))

        await client.verify_user_devices("@user:example.com")

        client.verify_device.assert_not_called()
        client._keyval_storage_gateway.put_json.assert_not_awaited()

    async def test_verify_user_devices_supports_device_store_without_get(self) -> None:
        client = self._client()
        client._config.matrix.security.device_trust.mode = "permissive"
        client.device_store = _DeviceStoreNoGet(
            {"@user:example.com": {"DEV-1": object(), "DEV-2": object()}}
        )
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)

        await client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 2)
        self.assertEqual(client._keyval_storage_gateway.put_json.await_count, 2)

        client.verify_device.reset_mock()
        client._keyval_storage_gateway.put_json.reset_mock()

        await client.verify_user_devices("@missing:example.com")

        client.verify_device.assert_not_called()
        client._keyval_storage_gateway.put_json.assert_not_awaited()

    async def test_verify_user_devices_strict_known_only_verifies_known_devices(
        self,
    ) -> None:
        client = self._client()
        client._config.matrix.security.device_trust.mode = "strict_known"
        client.device_store = _DeviceStore(
            {"@user:example.com": {"DEV-1": object(), "DEV-2": object()}}
        )
        client._keyval_storage_gateway.get_text = AsyncMock(
            return_value=json.dumps({"@user:example.com": ["DEV-1"]})
        )

        await client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 1)
        client._keyval_storage_gateway.put_json.assert_not_awaited()
        self.assertIn(
            "mode=strict_known",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_verify_user_devices_allowlist_mode(self) -> None:
        client = self._client()
        client._config.matrix.security.device_trust.mode = "allowlist"
        client._config.matrix.security.device_trust.allowlist = [
            {
                "user_id": "@user:example.com",
                "device_ids": ["DEV-2"],
            }
        ]
        client.device_store = _DeviceStore(
            {"@user:example.com": {"DEV-1": object(), "DEV-2": object()}}
        )
        client._keyval_storage_gateway.get_text = AsyncMock(return_value=None)

        await client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 1)
        client._keyval_storage_gateway.put_json.assert_not_awaited()
        self.assertIn(
            "reason=not_in_allowlist",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_resolve_device_trust_mode_defaults_and_invalid_values(self) -> None:
        client = self._client()
        del client._config.matrix.security
        self.assertEqual(
            client._resolve_device_trust_mode(),  # pylint: disable=protected-access
            "strict_known",
        )

        client._config.matrix.security = SimpleNamespace(
            device_trust=SimpleNamespace(mode=42)
        )
        self.assertEqual(
            client._resolve_device_trust_mode(),  # pylint: disable=protected-access
            "strict_known",
        )

        client._config.matrix.security.device_trust.mode = "unsupported"
        self.assertEqual(
            client._resolve_device_trust_mode(),  # pylint: disable=protected-access
            "strict_known",
        )

    async def test_resolve_device_trust_allowlist_parses_and_validates_entries(
        self,
    ) -> None:
        client = self._client()
        client._config.matrix.security.device_trust.allowlist = [
            {
                "user_id": "@user:example.com",
                "device_ids": ["DEV-1", 2],
            },
            SimpleNamespace(
                user_id="@user:example.com",
                device_ids=["DEV-2"],
            ),
            {
                "user_id": "@invalid:example.com",
                "device_ids": "DEV-3",
            },
            object(),
        ]
        self.assertEqual(
            client._resolve_device_trust_allowlist(),  # pylint: disable=protected-access
            {"@user:example.com": {"DEV-1", "2", "DEV-2"}},
        )

        client._config.matrix.security.device_trust.allowlist = "invalid"
        self.assertEqual(
            client._resolve_device_trust_allowlist(),  # pylint: disable=protected-access
            {},
        )

    async def test_is_direct_message_and_validate_message_paths(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")

        client.list_direct_rooms = AsyncMock(
            return_value=SimpleNamespace(
                rooms={"@user:example.com": ["!room:test"]},
            )
        )
        self.assertTrue(await client._is_direct_message(room.room_id))

        client._direct_room_ids.clear()
        client.list_direct_rooms = AsyncMock(return_value=SimpleNamespace(rooms={}))
        client.room_get_state = AsyncMock(return_value=SimpleNamespace(events=[]))
        self.assertFalse(await client._is_direct_message(room.room_id))

        client._is_direct_message = AsyncMock(return_value=True)
        own_message = SimpleNamespace(sender=client.user_id, event_id="$e1")
        self.assertFalse(await client._validate_message(room, own_message))

        client._is_direct_message = AsyncMock(return_value=False)
        not_direct = SimpleNamespace(sender="@user:example.com", event_id="$e2")
        self.assertFalse(await client._validate_message(room, not_direct))

        client._is_direct_message = AsyncMock(return_value=True)
        client.verify_user_devices = AsyncMock()
        valid_message = SimpleNamespace(sender="@user:example.com", event_id="$e3")
        self.assertTrue(await client._validate_message(room, valid_message))
        client.verify_user_devices.assert_awaited_with("@user:example.com")
        client.room_read_markers.assert_awaited_with("!room:test", "$e3", "$e3")

        malformed_sender = SimpleNamespace(sender="invalid-user-id", event_id="$e4")
        self.assertFalse(await client._validate_message(room, malformed_sender))
        self.assertIn(
            "Reason: Malformed sender.",
            client._logging_gateway.warning.call_args.args[0],
        )
        self.assertEqual(
            client._matrix_metrics["matrix.messages.ignored.self_message"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.messages.ignored.room_not_direct"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.messages.accepted.validated"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.messages.rejected.malformed_sender"], 1  # pylint: disable=protected-access
        )

    async def test_is_direct_message_handles_direct_rooms_without_legacy_fallback(
        self,
    ) -> None:
        client = self._client()

        client.list_direct_rooms = AsyncMock(return_value=SimpleNamespace(rooms="invalid"))
        self.assertFalse(await client._is_direct_message("!room:test"))

        client.list_direct_rooms = AsyncMock(
            return_value=SimpleNamespace(rooms={"@u:example.com": ["!room:test"]})
        )
        self.assertTrue(await client._is_direct_message("!room:test"))

        client._direct_room_ids.clear()
        client.list_direct_rooms = AsyncMock(return_value=SimpleNamespace(rooms={}))
        self.assertFalse(await client._is_direct_message("!room:test"))

    async def test_is_direct_message_cache_hit_and_multi_user_scan(self) -> None:
        client = self._client()

        client._direct_room_ids.add("!cached:test")
        self.assertTrue(await client._is_direct_message("!cached:test"))

        client._direct_room_ids.clear()
        client.list_direct_rooms = AsyncMock(
            return_value=SimpleNamespace(
                rooms={
                    "@a:example.com": ["!other:test"],
                    "@b:example.com": ["!target:test"],
                }
            )
        )
        self.assertTrue(await client._is_direct_message("!target:test"))
        self.assertIn("!target:test", client._direct_room_ids)

    async def test_normalize_and_load_direct_rooms(self) -> None:
        client = self._client()
        self.assertEqual(
            client._normalize_direct_rooms(  # pylint: disable=protected-access
                {"@u:example.com": ["!a:test", 2], "@bad:example.com": "invalid"}
            ),
            {"@u:example.com": ["!a:test", "2"]},
        )
        self.assertEqual(
            client._normalize_direct_rooms(  # pylint: disable=protected-access
                ["invalid"]
            ),
            {},
        )

        client.list_direct_rooms = AsyncMock(
            return_value=SimpleNamespace(
                rooms={
                    "@u:example.com": ["!room:test"],
                    "@bad:example.com": "invalid",
                }
            )
        )
        self.assertEqual(
            await client._load_direct_rooms(),  # pylint: disable=protected-access
            {"@u:example.com": ["!room:test"]},
        )

        client._logging_gateway.debug.reset_mock()
        client.list_direct_rooms = AsyncMock(return_value=matrix_mod.DirectRoomsResponse({}))
        self.assertEqual(
            await client._load_direct_rooms(),  # pylint: disable=protected-access
            {},
        )
        client._logging_gateway.debug.assert_not_called()

        client._logging_gateway.debug.reset_mock()
        client.list_direct_rooms = AsyncMock(return_value=SimpleNamespace())
        self.assertEqual(
            await client._load_direct_rooms(),  # pylint: disable=protected-access
            {},
        )
        self.assertIn(
            "direct room list unavailable",
            client._logging_gateway.debug.call_args.args[0],
        )

        client.list_direct_rooms = AsyncMock(side_effect=RuntimeError("boom"))
        self.assertEqual(
            await client._load_direct_rooms(),  # pylint: disable=protected-access
            {},
        )
        self.assertIn(
            "lookup failed",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_persist_direct_rooms_handles_success_failure_and_exception(self) -> None:
        client = self._client()

        with patch.object(matrix_mod.Api, "_build_path", return_value="/m.direct"):
            client._send = AsyncMock(return_value=matrix_mod.EmptyResponse())
            self.assertTrue(
                await client._persist_direct_rooms(  # pylint: disable=protected-access
                    {"@u:example.com": ["!room:test"]}
                )
            )
            client._send.assert_awaited_once_with(
                matrix_mod.EmptyResponse,
                "PUT",
                "/m.direct",
                json.dumps({"@u:example.com": ["!room:test"]}),
            )

            client._send = AsyncMock(return_value=object())
            self.assertFalse(
                await client._persist_direct_rooms(  # pylint: disable=protected-access
                    {"@u:example.com": ["!room:test"]}
                )
            )
            self.assertIn(
                "response=object",
                client._logging_gateway.warning.call_args.args[0],
            )

            client._send = AsyncMock(side_effect=RuntimeError("boom"))
            self.assertFalse(
                await client._persist_direct_rooms(  # pylint: disable=protected-access
                    {"@u:example.com": ["!room:test"]}
                )
            )
            self.assertIn(
                "error=RuntimeError: boom",
                client._logging_gateway.warning.call_args.args[0],
            )

    async def test_mark_room_as_direct_updates_cache_and_persists(self) -> None:
        client = self._client()
        client._load_direct_rooms = AsyncMock(  # pylint: disable=protected-access
            return_value={"@u:example.com": ["!old:test"]}
        )
        client._persist_direct_rooms = AsyncMock(  # pylint: disable=protected-access
            return_value=True
        )

        await client._mark_room_as_direct(  # pylint: disable=protected-access
            "@u:example.com", "!room:test"
        )
        client._persist_direct_rooms.assert_awaited_once_with(  # pylint: disable=protected-access
            {"@u:example.com": ["!old:test", "!room:test"]}
        )
        self.assertIn("!room:test", client._direct_room_ids)  # pylint: disable=protected-access

        client._persist_direct_rooms.reset_mock()  # pylint: disable=protected-access
        await client._mark_room_as_direct(  # pylint: disable=protected-access
            "@u:example.com", "!room:test"
        )
        client._persist_direct_rooms.assert_not_called()  # pylint: disable=protected-access

        await client._mark_room_as_direct(  # pylint: disable=protected-access
            None, "!sender-optional:test"
        )
        self.assertIn(  # pylint: disable=protected-access
            "!sender-optional:test",
            client._direct_room_ids,
        )

        client._load_direct_rooms = AsyncMock(return_value={})  # pylint: disable=protected-access
        client._persist_direct_rooms = AsyncMock(  # pylint: disable=protected-access
            return_value=False
        )
        await client._mark_room_as_direct(  # pylint: disable=protected-access
            "@u:example.com",
            "!persist-fail:test",
        )
        self.assertIn(
            "direct room marker not persisted",
            client._logging_gateway.warning.call_args.args[0],
        )

        direct_room_ids_before = set(client._direct_room_ids)  # pylint: disable=protected-access
        await client._mark_room_as_direct(  # pylint: disable=protected-access
            "@u:example.com",
            " ",
        )
        self.assertEqual(client._direct_room_ids, direct_room_ids_before)  # pylint: disable=protected-access

    async def test_cb_invite_member_event_reject_and_accept_paths(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client.verify_user_devices = AsyncMock()
        client._mark_room_as_direct = AsyncMock()

        event = SimpleNamespace(content={"membership": "join"}, sender="@u:example.com")
        await client._cb_invite_member_event(room, event)
        client.room_leave.assert_not_called()

        event = SimpleNamespace(
            content={"membership": "invite", "is_direct": True},
            sender="@u:blocked.com",
        )
        await client._cb_invite_member_event(room, event)
        client.room_leave.assert_awaited()

        client.room_leave.reset_mock()
        client._config.mugen.beta.active = True
        event = SimpleNamespace(
            content={"membership": "invite", "is_direct": True},
            sender="@u:example.com",
        )
        await client._cb_invite_member_event(room, event)
        client.room_leave.assert_awaited()

        client.room_leave.reset_mock()
        client._config.mugen.beta.active = False
        event = SimpleNamespace(
            content={"membership": "invite"}, sender="@u:example.com"
        )
        await client._cb_invite_member_event(room, event)
        client.room_leave.assert_awaited()

        client.room_leave.reset_mock()
        client.join = AsyncMock()
        client.room_put_state = AsyncMock()
        client.get_profile = AsyncMock(return_value=_FakeProfileGetResponse("User"))
        event = SimpleNamespace(
            content={"membership": "invite", "is_direct": True},
            sender="@u:example.com",
        )
        await client._cb_invite_member_event(room, event)

        client.join.assert_awaited_once_with("!room:test")
        client._mark_room_as_direct.assert_awaited_once_with(
            "@u:example.com", "!room:test"
        )
        client._user_service.add_known_user.assert_awaited_once_with(
            "@u:example.com",
            "User",
            "!room:test",
        )
        self.assertEqual(
            client._matrix_metrics["matrix.invites.ignored.membership_not_invite"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.invites.rejected.domain_not_allowed"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.invites.rejected.non_beta_user"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.invites.rejected.not_direct_message"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.invites.accepted.joined"], 1  # pylint: disable=protected-access
        )

    async def test_cb_invite_member_event_rejects_malformed_sender(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")

        event = SimpleNamespace(
            content={"membership": "invite", "is_direct": True},
            sender="malformed",
        )
        await client._cb_invite_member_event(room, event)

        client.room_leave.assert_awaited_once_with("!room:test")
        self.assertIn(
            "Reason: Malformed sender.",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_cb_invite_member_event_accepts_non_direct_when_configured(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._config.matrix.invites.direct_only = False
        client.verify_user_devices = AsyncMock()
        client._mark_room_as_direct = AsyncMock()
        client.get_profile = AsyncMock(return_value=_FakeProfileGetResponse("User"))
        event = SimpleNamespace(content={"membership": "invite"}, sender="@u:example.com")

        await client._cb_invite_member_event(room, event)

        client.room_leave.assert_not_called()
        client.join.assert_awaited_once_with("!room:test")
        client._mark_room_as_direct.assert_awaited_once_with(
            "@u:example.com", "!room:test"
        )

    async def test_parse_sender_domain(self) -> None:
        client = self._client()
        self.assertEqual(
            client._parse_sender_domain("@user:example.com"),  # pylint: disable=protected-access
            "example.com",
        )
        self.assertEqual(
            client._parse_sender_domain("@user:example.com:8448"),  # pylint: disable=protected-access
            "example.com:8448",
        )
        self.assertIsNone(
            client._parse_sender_domain("@user"),  # pylint: disable=protected-access
        )
        self.assertIsNone(
            client._parse_sender_domain("user:example.com"),  # pylint: disable=protected-access
        )
        self.assertIsNone(
            client._parse_sender_domain(123),  # pylint: disable=protected-access
        )

    async def test_cb_invite_member_event_beta_user_without_profile_object(
        self,
    ) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._config.mugen.beta.active = True
        client.verify_user_devices = AsyncMock()
        client._mark_room_as_direct = AsyncMock()
        client.get_profile = AsyncMock(return_value=object())
        event = SimpleNamespace(
            content={"membership": "invite", "is_direct": True},
            sender="@beta:example.com",
        )

        await client._cb_invite_member_event(room, event)

        client.join.assert_awaited_once_with("!room:test")
        client._mark_room_as_direct.assert_awaited_once_with(
            "@beta:example.com", "!room:test"
        )
        client._user_service.add_known_user.assert_not_awaited()

    async def test_callback_skip_logging_for_stubbed_paths(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        callback_invocations = [
            ("_cb_megolm_event", (room, object())),
            ("_cb_invite_alias_event", (room, object())),
            ("_cb_invite_name_event", (room, object())),
            ("_cb_room_create_event", (room, object())),
            ("_cb_key_verification_event", (object(),)),
            ("_cb_room_key_event", (object(),)),
            ("_cb_room_key_request", (object(),)),
            ("_cb_room_member_event", (room, object())),
            ("_cb_tag_event", (object(),)),
        ]

        for callback_name, args in callback_invocations:
            client._logging_gateway.debug.reset_mock()
            callback = getattr(client, callback_name)
            await callback(*args)
            client._logging_gateway.debug.assert_called_once()
            log_message = client._logging_gateway.debug.call_args.args[0]
            self.assertIn("Matrix callback skipped.", log_message)
            self.assertIn(f"callback={callback_name}", log_message)
            self.assertIn("reason=unsupported_dm_scope", log_message)

    async def test_track_matrix_decision_logs_reason_codes_and_counts(self) -> None:
        client = self._client()

        client._track_matrix_decision(  # pylint: disable=protected-access
            domain="messages",
            action="ignored",
            reason="room_not_direct",
            room_id="!room:test",
            sender="@user:example.com",
        )
        client._track_matrix_decision(  # pylint: disable=protected-access
            domain="messages",
            action="ignored",
            reason="room_not_direct",
            room_id="!room:test",
            sender="@user:example.com",
        )

        self.assertEqual(
            client._matrix_metrics["matrix.messages.ignored.room_not_direct"], 2  # pylint: disable=protected-access
        )
        log_message = client._logging_gateway.debug.call_args.args[0]
        self.assertIn("Matrix decision domain=messages action=ignored", log_message)
        self.assertIn("reason=room_not_direct", log_message)
        self.assertIn("room_id=!room:test", log_message)
        self.assertIn("sender=@user:example.com", log_message)

    async def test_non_core_callbacks_dispatch_to_matrix_event_hook(self) -> None:
        client = self._client()
        client._matrix_ipc_queue = asyncio.Queue(maxsize=32)
        client._start_matrix_ipc_worker = Mock()
        room = SimpleNamespace(room_id="!room:test")
        callback_invocations = [
            ("_cb_megolm_event", (room, SimpleNamespace(sender="@u:example.com"))),
            (
                "_cb_invite_alias_event",
                (room, SimpleNamespace(content={"alias": "#room:example.com"})),
            ),
            ("_cb_invite_name_event", (room, SimpleNamespace(content={"name": "x"}))),
            ("_cb_room_create_event", (room, SimpleNamespace(content={"creator": "x"}))),
            ("_cb_key_verification_event", (SimpleNamespace(sender="@u:example.com"),)),
            ("_cb_room_key_event", (SimpleNamespace(source={"content": {"a": 1}}),)),
            ("_cb_room_key_request", (SimpleNamespace(sender="@u:example.com"),)),
            ("_cb_room_member_event", (room, SimpleNamespace(content={"membership": "leave"}))),
            ("_cb_tag_event", (SimpleNamespace(content={"tags": {}}),)),
        ]

        for callback_name, args in callback_invocations:
            callback = getattr(client, callback_name)
            await callback(*args)
            self.assertEqual(client._matrix_ipc_queue.qsize(), 1)
            payload = client._matrix_ipc_queue.get_nowait()
            self.assertEqual(payload.platform, "matrix")
            self.assertEqual(payload.command, client._matrix_event_hook_command)
            self.assertEqual(payload.data["callback"], callback_name)
            self.assertEqual(
                payload.data["reason"],
                client._callback_skip_reason_dm_scope,
            )
            self.assertIn("event_type", payload.data)
            self.assertNotIn("event", payload.data)

    async def test_dispatch_matrix_event_hook_handles_missing_ipc_service_paths(
        self,
    ) -> None:
        client = self._client()

        client._ipc_service = None
        await client._dispatch_matrix_event_hook(  # pylint: disable=protected-access
            callback_name="_cb_tag_event",
            event=SimpleNamespace(),
        )

        client._ipc_service = SimpleNamespace(handle_ipc_request=None)
        await client._dispatch_matrix_event_hook(  # pylint: disable=protected-access
            callback_name="_cb_tag_event",
            event=SimpleNamespace(),
        )

        non_awaitable_handler = Mock(return_value=None)
        client._ipc_service = SimpleNamespace(handle_ipc_request=non_awaitable_handler)
        client._start_matrix_ipc_worker = Mock()
        client._matrix_ipc_queue = None
        await client._dispatch_matrix_event_hook(  # pylint: disable=protected-access
            callback_name="_cb_tag_event",
            event=SimpleNamespace(),
        )
        non_awaitable_handler.assert_not_called()
        self.assertEqual(
            client._matrix_metrics["matrix.ipc.dispatch.queue_unavailable_drop_new"],  # pylint: disable=protected-access
            1,
        )

    async def test_non_core_callback_logs_warning_on_queue_drop(self) -> None:
        client = self._client()
        client._ipc_service = SimpleNamespace(handle_ipc_request=AsyncMock())
        client._start_matrix_ipc_worker = Mock()
        client._matrix_ipc_queue = asyncio.Queue(maxsize=1)
        client._matrix_ipc_queue.put_nowait(
            IPCCommandRequest(platform="matrix", command="matrix_event", data={})
        )

        await client._cb_tag_event(SimpleNamespace())

        warning_messages = [
            call.args[0] for call in client._logging_gateway.warning.call_args_list
        ]
        self.assertTrue(
            any(
                "Matrix event extension queue full; dropping event." in message
                for message in warning_messages
            )
        )

    async def test_non_core_callback_integration_dispatches_to_ipc_extension(
        self,
    ) -> None:
        client = self._client()
        ipc_service = DefaultIPCService(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )
        extension = _RecordingMatrixEventIPCExtension()
        ipc_service.bind_ipc_extension(extension)
        client._ipc_service = ipc_service

        room = SimpleNamespace(room_id="!room:test")
        event = SimpleNamespace(content={"membership": "join"})
        await client._cb_room_member_event(room, event)
        await asyncio.sleep(0.05)

        self.assertEqual(len(extension.events), 1)
        self.assertEqual(extension.events[0]["callback"], "_cb_room_member_event")
        self.assertEqual(extension.events[0]["event_type"], "SimpleNamespace")
        self.assertEqual(
            extension.events[0]["reason"],
            client._callback_skip_reason_dm_scope,
        )
        self.assertEqual(extension.events[0]["room_id"], "!room:test")

    async def test_cb_room_message_dispatches_text_and_media_handlers(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._validate_message = AsyncMock(return_value=True)
        client._download_file = AsyncMock(return_value="/tmp/file")
        client._process_message_responses = AsyncMock(return_value=None)
        client._messaging_service.handle_audio_message = AsyncMock(
            return_value=[{"type": "text", "content": "audio"}]
        )
        client._messaging_service.handle_file_message = AsyncMock(return_value=[])
        client._messaging_service.handle_image_message = AsyncMock(return_value=[])
        client._messaging_service.handle_text_message = AsyncMock(return_value=[])
        client._messaging_service.handle_video_message = AsyncMock(return_value=[])

        with patch.multiple(
            matrix_mod,
            RoomEncryptedAudio=_FakeEncryptedAudio,
            RoomEncryptedFile=_FakeEncryptedFile,
            RoomEncryptedImage=_FakeEncryptedImage,
            RoomEncryptedVideo=_FakeEncryptedVideo,
            RoomMessageText=_FakeTextMessage,
        ):
            await client._cb_room_message(room, _FakeEncryptedAudio())
            await client._cb_room_message(room, _FakeEncryptedFile())
            await client._cb_room_message(room, _FakeEncryptedImage())
            await client._cb_room_message(room, _FakeTextMessage(body="hello"))
            await client._cb_room_message(room, _FakeEncryptedVideo())

        client._messaging_service.handle_audio_message.assert_awaited()
        client._messaging_service.handle_file_message.assert_awaited()
        client._messaging_service.handle_image_message.assert_awaited()
        client._messaging_service.handle_text_message.assert_awaited()
        client._messaging_service.handle_video_message.assert_awaited()
        self.assertEqual(client._process_message_responses.await_count, 5)
        self.assertEqual(client.room_typing.await_count, 10)

    async def test_cb_room_message_returns_early_when_validation_fails(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._validate_message = AsyncMock(return_value=False)
        client._process_message_responses = AsyncMock(return_value=None)

        with patch.object(matrix_mod, "RoomMessageText", _FakeTextMessage):
            await client._cb_room_message(room, _FakeTextMessage())

        client._process_message_responses.assert_not_called()
        client.room_typing.assert_not_awaited()

    async def test_cb_room_message_media_without_download_and_unknown_type(
        self,
    ) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._validate_message = AsyncMock(return_value=True)
        client._download_file = AsyncMock(return_value=None)
        client._process_message_responses = AsyncMock(return_value=None)
        client._messaging_service.handle_audio_message = AsyncMock(return_value=[])
        client._messaging_service.handle_file_message = AsyncMock(return_value=[])
        client._messaging_service.handle_image_message = AsyncMock(return_value=[])
        client._messaging_service.handle_video_message = AsyncMock(return_value=[])
        unknown_message = SimpleNamespace(sender="@user:example.com")

        with patch.multiple(
            matrix_mod,
            RoomEncryptedAudio=_FakeEncryptedAudio,
            RoomEncryptedFile=_FakeEncryptedFile,
            RoomEncryptedImage=_FakeEncryptedImage,
            RoomEncryptedVideo=_FakeEncryptedVideo,
            RoomMessageText=_FakeTextMessage,
        ):
            await client._cb_room_message(room, _FakeEncryptedAudio())
            await client._cb_room_message(room, _FakeEncryptedFile())
            await client._cb_room_message(room, _FakeEncryptedImage())
            await client._cb_room_message(room, _FakeEncryptedVideo())
            await client._cb_room_message(room, unknown_message)

        client._messaging_service.handle_audio_message.assert_not_called()
        client._messaging_service.handle_file_message.assert_not_called()
        client._messaging_service.handle_image_message.assert_not_called()
        client._messaging_service.handle_video_message.assert_not_called()
        self.assertEqual(client._process_message_responses.await_count, 5)
        self.assertEqual(client.room_typing.await_count, 10)

    async def test_cb_room_message_cleans_up_media_file_when_handler_raises(
        self,
    ) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._validate_message = AsyncMock(return_value=True)
        client._download_file = AsyncMock(return_value="/tmp/file")
        client._cleanup_temp_file = Mock()
        client._process_message_responses = AsyncMock(return_value=None)
        client._messaging_service.handle_audio_message = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        with (
            patch.object(matrix_mod, "RoomEncryptedAudio", _FakeEncryptedAudio),
            self.assertRaises(RuntimeError),
        ):
            await client._cb_room_message(room, _FakeEncryptedAudio())

        client._cleanup_temp_file.assert_called_once_with("/tmp/file")
        client._process_message_responses.assert_not_awaited()
        self.assertEqual(client.room_typing.await_count, 2)
        self.assertEqual(client.room_typing.await_args_list[0].args, ("!room:test", True))
        self.assertEqual(client.room_typing.await_args_list[1].args, ("!room:test", False))

    async def test_cb_room_message_ignores_typing_signal_errors(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._validate_message = AsyncMock(return_value=True)
        client._process_message_responses = AsyncMock(return_value=None)
        client._messaging_service.handle_text_message = AsyncMock(return_value=[])
        client.room_typing = AsyncMock(side_effect=RuntimeError("typing boom"))

        with patch.object(matrix_mod, "RoomMessageText", _FakeTextMessage):
            await client._cb_room_message(room, _FakeTextMessage(body="hello"))

        client._messaging_service.handle_text_message.assert_awaited_once()
        client._process_message_responses.assert_awaited_once()

    async def test_process_message_responses_dispatches_by_response_type(self) -> None:
        client = self._client()
        client._send_audio_message = AsyncMock()
        client._send_file_message = AsyncMock()
        client._send_image_message = AsyncMock()
        client._send_text_message = AsyncMock()
        client._send_video_message = AsyncMock()

        responses = [
            {"type": "audio", "file": {"name": "a"}, "info": {"duration": 1}},
            {"type": "file", "file": {"name": "f"}},
            {"type": "image", "file": {"name": "i"}, "info": {"height": 1, "width": 2}},
            {"type": "text", "content": "hello"},
            {"type": "video", "file": {"name": "v"}, "info": {"duration": 1}},
            {"type": "unknown"},
        ]

        await client._process_message_responses("!room:test", responses)

        client._send_audio_message.assert_awaited_once()
        client._send_file_message.assert_awaited_once()
        client._send_image_message.assert_awaited_once()
        client._send_text_message.assert_awaited_once()
        client._send_video_message.assert_awaited_once()

    async def test_send_message_helpers_send_expected_payloads(self) -> None:
        client = self._client()
        encryption_keys = {
            "hashes": {"sha256": "abc"},
            "iv": "iv",
            "key": {"k": "k"},
            "v": "v2",
        }
        file_payload = {
            "name": "sample.bin",
            "size": 12,
            "type": "application/octet-stream",
        }
        with patch.object(matrix_mod, "UploadResponse", _FakeUploadResponse):
            client._upload_file = AsyncMock(
                return_value=(_FakeUploadResponse(), encryption_keys)
            )
            await client._send_audio_message(
                "!room:test", file_payload, {"duration": 5}
            )
            await client._send_file_message("!room:test", file_payload)
            await client._send_image_message(
                "!room:test",
                file_payload,
                {"height": 10, "width": 20},
            )
            await client._send_video_message(
                "!room:test",
                file_payload,
                {"duration": 3, "height": 10, "width": 20},
            )

        self.assertEqual(client.room_send.await_count, 4)

        client.room_send = AsyncMock(side_effect=LocalProtocolError("boom"))
        await client._send_text_message("!room:test", "hello")

    async def test_send_text_message_retries_for_unverified_self_device(self) -> None:
        client = self._client()
        client.room_send = AsyncMock(
            side_effect=[
                matrix_mod.OlmUnverifiedDeviceError(
                    SimpleNamespace(user_id=client.user_id, device_id="DEV-1")
                ),
                object(),
            ]
        )

        await client._send_text_message("!room:test", "hello")

        self.assertEqual(client.room_send.await_count, 2)
        first_send_kwargs = client.room_send.await_args_list[0].kwargs
        second_send_kwargs = client.room_send.await_args_list[1].kwargs
        self.assertEqual(first_send_kwargs["room_id"], "!room:test")
        self.assertNotIn("ignore_unverified_devices", first_send_kwargs)
        self.assertTrue(second_send_kwargs["ignore_unverified_devices"])
        self.assertIn(
            "retrying with ignore_unverified_devices",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_send_text_message_retries_for_unverified_self_device_id_alias(
        self,
    ) -> None:
        client = self._client()
        client.room_send = AsyncMock(
            side_effect=[
                matrix_mod.OlmUnverifiedDeviceError(
                    SimpleNamespace(user_id=client.user_id, id="DEV-ID-1")
                ),
                object(),
            ]
        )

        await client._send_text_message("!room:test", "hello")

        self.assertEqual(client.room_send.await_count, 2)
        self.assertTrue(
            client.room_send.await_args_list[1].kwargs["ignore_unverified_devices"]
        )
        self.assertIn(
            "device_id=DEV-ID-1",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_send_text_message_does_not_retry_for_unverified_non_self_device(
        self,
    ) -> None:
        client = self._client()
        client.room_send = AsyncMock(
            side_effect=matrix_mod.OlmUnverifiedDeviceError(
                SimpleNamespace(user_id="@other:example.com", device_id="DEV-1")
            )
        )

        await client._send_text_message("!room:test", "hello")

        self.assertEqual(client.room_send.await_count, 1)
        self.assertIn(
            "Error sending text message",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_send_media_helpers_return_early_when_upload_is_none(self) -> None:
        client = self._client()
        client._upload_file = AsyncMock(return_value=(None, None))
        file_payload = {
            "name": "sample.bin",
            "size": 12,
            "type": "application/octet-stream",
        }

        await client._send_audio_message("!room:test", file_payload, {"duration": 5})
        await client._send_file_message("!room:test", file_payload)
        await client._send_image_message(
            "!room:test",
            file_payload,
            {"height": 10, "width": 20},
        )
        await client._send_video_message(
            "!room:test",
            file_payload,
            {"duration": 3, "height": 10, "width": 20},
        )

        client.room_send.assert_not_called()

    async def test_send_media_helpers_skip_non_upload_response(self) -> None:
        client = self._client()
        encryption_keys = {
            "hashes": {"sha256": "abc"},
            "iv": "iv",
            "key": {"k": "k"},
            "v": "v2",
        }
        client._upload_file = AsyncMock(return_value=(object(), encryption_keys))
        file_payload = {
            "name": "sample.bin",
            "size": 12,
            "type": "application/octet-stream",
        }

        await client._send_audio_message("!room:test", file_payload, {"duration": 5})
        await client._send_file_message("!room:test", file_payload)
        await client._send_image_message(
            "!room:test",
            file_payload,
            {"height": 10, "width": 20},
        )
        await client._send_video_message(
            "!room:test",
            file_payload,
            {"duration": 3, "height": 10, "width": 20},
        )

        client.room_send.assert_not_called()

    async def test_send_media_helpers_log_warning_when_send_raises(self) -> None:
        client = self._client()
        encryption_keys = {
            "hashes": {"sha256": "abc"},
            "iv": "iv",
            "key": {"k": "k"},
            "v": "v2",
        }
        file_payload = {
            "name": "sample.bin",
            "size": 12,
            "type": "application/octet-stream",
        }
        client._upload_file = AsyncMock(
            return_value=(_FakeUploadResponse(), encryption_keys)
        )
        client.room_send = AsyncMock(side_effect=LocalProtocolError("boom"))

        with (
            patch.object(matrix_mod, "UploadResponse", _FakeUploadResponse),
            patch.object(matrix_mod.traceback, "print_exc"),
        ):
            await client._send_audio_message(
                "!room:test", file_payload, {"duration": 5}
            )
            await client._send_file_message("!room:test", file_payload)
            await client._send_image_message(
                "!room:test",
                file_payload,
                {"height": 10, "width": 20},
            )
            await client._send_video_message(
                "!room:test",
                file_payload,
                {"duration": 3, "height": 10, "width": 20},
            )

        self.assertGreaterEqual(client._logging_gateway.warning.call_count, 4)

    async def test_upload_file_and_upload_helpers_route_correctly(self) -> None:
        client = self._client()
        in_mem = {
            "uri": BytesIO(b"abc"),
            "type": "text/plain",
            "name": "a.txt",
            "size": 3,
        }
        on_disk = {"uri": "/tmp/file", "type": "text/plain", "name": "b.txt", "size": 4}

        client._upload_in_memory_file = AsyncMock(return_value=("mem", {"a": 1}))
        client._upload_disk_file = AsyncMock(return_value=("disk", {"b": 1}))

        self.assertEqual(await client._upload_file(in_mem), ("mem", {"a": 1}))
        self.assertEqual(await client._upload_file(on_disk), ("disk", {"b": 1}))

        helper_client = self._client()
        helper_client.upload = AsyncMock(return_value=("resp", {"k": 1}))
        self.assertEqual(
            await helper_client._upload_in_memory_file(in_mem),
            ("resp", {"k": 1}),
        )

        fake_handle = object()
        with patch.object(
            matrix_mod.aiofiles,
            "open",
            return_value=_FakeAsyncFileCtx(fake_handle),
        ):
            self.assertEqual(
                await helper_client._upload_disk_file(on_disk),
                ("resp", {"k": 1}),
            )
        helper_client.upload.assert_awaited()

    async def test_download_file_handles_missing_extension_and_success_path(
        self,
    ) -> None:
        client = self._client()
        file_meta = {
            "url": "mxc://example/file",
            "key": {"k": "k"},
            "hashes": {"sha256": "sha"},
            "iv": "iv",
        }

        with patch.object(matrix_mod.mimetypes, "guess_extension", return_value=None):
            self.assertIsNone(
                await client._download_file(
                    file=file_meta,
                    info={"mimetype": "application/octet-stream"},
                )
            )
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.extension_unknown"], 1  # pylint: disable=protected-access
        )

        async def _fake_download(url: str, save_to: str):
            with open(save_to, "wb") as f:
                f.write(b"encrypted")
            return _FakeDiskDownloadResponse()

        client.download = AsyncMock(side_effect=_fake_download)
        with (
            patch.object(matrix_mod.mimetypes, "guess_extension", return_value=".txt"),
            patch.object(matrix_mod, "DiskDownloadResponse", _FakeDiskDownloadResponse),
            patch.object(
                matrix_mod.nio.crypto,
                "decrypt_attachment",
                return_value=b"decrypted",
            ),
        ):
            output_path = await client._download_file(
                file=file_meta,
                info={"mimetype": "text/plain"},
            )

        self.assertIsNotNone(output_path)
        with open(output_path, "rb") as f:
            self.assertEqual(f.read(), b"decrypted")
        os.unlink(output_path)
        self.assertEqual(
            client._matrix_metrics["matrix.media.accepted.downloaded"], 1  # pylint: disable=protected-access
        )

    async def test_download_file_returns_none_for_unexpected_download_response(
        self,
    ) -> None:
        client = self._client()
        file_meta = {
            "url": "mxc://example/file",
            "key": {"k": "k"},
            "hashes": {"sha256": "sha"},
            "iv": "iv",
        }
        client.download = AsyncMock(return_value=object())

        with patch.object(matrix_mod.mimetypes, "guess_extension", return_value=".txt"):
            output_path = await client._download_file(
                file=file_meta,
                info={"mimetype": "text/plain"},
            )

        self.assertIsNone(output_path)
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.download_response_unexpected"], 1  # pylint: disable=protected-access
        )

    async def test_media_config_resolution_and_mimetype_matching(self) -> None:
        client = self._client()

        client._config.matrix.media = SimpleNamespace(
            max_download_bytes="invalid",
            allowed_mimetypes="text/plain",
        )
        self.assertEqual(
            client._resolve_media_max_download_bytes(),  # pylint: disable=protected-access
            client._default_media_max_download_bytes,  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._resolve_media_allowed_mimetypes(),  # pylint: disable=protected-access
            list(client._default_media_allowed_mimetypes),  # pylint: disable=protected-access
        )

        client._config.matrix.media.max_download_bytes = 0
        self.assertEqual(
            client._resolve_media_max_download_bytes(),  # pylint: disable=protected-access
            client._default_media_max_download_bytes,  # pylint: disable=protected-access
        )

        client._config.matrix.media.max_download_bytes = 1024
        self.assertEqual(
            client._resolve_media_max_download_bytes(),  # pylint: disable=protected-access
            1024,
        )

        client._config.matrix.media.allowed_mimetypes = []
        self.assertEqual(
            client._resolve_media_allowed_mimetypes(),  # pylint: disable=protected-access
            list(client._default_media_allowed_mimetypes),  # pylint: disable=protected-access
        )

        client._config.matrix.media.allowed_mimetypes = ["application/pdf"]
        self.assertTrue(
            client._media_mimetype_allowed(  # pylint: disable=protected-access
                "application/pdf"
            )
        )
        self.assertFalse(
            client._media_mimetype_allowed(  # pylint: disable=protected-access
                "image/png"
            )
        )

        client._config.matrix.media.allowed_mimetypes = [" image/* "]
        self.assertTrue(
            client._media_mimetype_allowed(  # pylint: disable=protected-access
                "image/png"
            )
        )

    async def test_cleanup_temp_file_handles_empty_missing_and_os_error(self) -> None:
        client = self._client()

        client._cleanup_temp_file(None)  # pylint: disable=protected-access
        client._cleanup_temp_file("   ")  # pylint: disable=protected-access

        with tempfile.NamedTemporaryFile(delete=False) as tf:
            temp_path = tf.name

        self.assertTrue(os.path.exists(temp_path))
        client._cleanup_temp_file(temp_path)  # pylint: disable=protected-access
        self.assertFalse(os.path.exists(temp_path))

        with (
            patch.object(matrix_mod.os.path, "isfile", return_value=True),
            patch.object(matrix_mod.os, "unlink", side_effect=OSError("denied")),
        ):
            client._cleanup_temp_file("/tmp/blocked")  # pylint: disable=protected-access

        self.assertGreaterEqual(client._logging_gateway.warning.call_count, 1)

    async def test_download_file_rejects_invalid_metadata_mimetype_and_size(
        self,
    ) -> None:
        client = self._client()
        client._config.matrix.media = SimpleNamespace(
            max_download_bytes=5,
            allowed_mimetypes=["text/plain"],
        )
        file_meta = {
            "url": "mxc://example/file",
            "key": {"k": "k"},
            "hashes": {"sha256": "sha"},
            "iv": "iv",
        }

        self.assertIsNone(
            await client._download_file(file=file_meta, info=["invalid"])  # pylint: disable=protected-access
        )
        self.assertIsNone(
            await client._download_file(file=file_meta, info={})  # pylint: disable=protected-access
        )

        client._config.matrix.media.allowed_mimetypes = ["image/*"]
        self.assertIsNone(
            await client._download_file(  # pylint: disable=protected-access
                file=file_meta,
                info={"mimetype": "text/plain"},
            )
        )

        client._config.matrix.media.allowed_mimetypes = ["text/plain"]
        self.assertIsNone(
            await client._download_file(  # pylint: disable=protected-access
                file=file_meta,
                info={"mimetype": "text/plain", "size": 6},
            )
        )

        async def _fake_download(url: str, save_to: str):
            with open(save_to, "wb") as f:
                f.write(b"123456")
            return _FakeDiskDownloadResponse()

        client.download = AsyncMock(side_effect=_fake_download)
        with (
            patch.object(matrix_mod.mimetypes, "guess_extension", return_value=".txt"),
            patch.object(matrix_mod, "DiskDownloadResponse", _FakeDiskDownloadResponse),
        ):
            self.assertIsNone(
                await client._download_file(  # pylint: disable=protected-access
                    file=file_meta,
                    info={"mimetype": "text/plain", "size": 4},
                )
            )
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.invalid_metadata"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.missing_mimetype"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.mimetype_not_allowed"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.declared_size_exceeded"], 1  # pylint: disable=protected-access
        )
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.downloaded_size_exceeded"], 1  # pylint: disable=protected-access
        )

    async def test_download_file_returns_none_when_decryption_fails(self) -> None:
        client = self._client()
        client._config.matrix.media = SimpleNamespace(
            max_download_bytes=1024,
            allowed_mimetypes=["text/plain"],
        )
        file_meta = {
            "url": "mxc://example/file",
            "key": {"k": "k"},
            "hashes": {"sha256": "sha"},
            "iv": "iv",
        }

        async def _fake_download(url: str, save_to: str):
            with open(save_to, "wb") as f:
                f.write(b"encrypted")
            return _FakeDiskDownloadResponse()

        client.download = AsyncMock(side_effect=_fake_download)

        with (
            patch.object(matrix_mod.mimetypes, "guess_extension", return_value=".txt"),
            patch.object(matrix_mod, "DiskDownloadResponse", _FakeDiskDownloadResponse),
            patch.object(
                matrix_mod.nio.crypto,
                "decrypt_attachment",
                side_effect=ValueError("bad decrypt"),
            ),
        ):
            self.assertIsNone(
                await client._download_file(  # pylint: disable=protected-access
                    file=file_meta,
                    info={"mimetype": "text/plain", "size": 4},
                )
            )

        self.assertGreaterEqual(client._logging_gateway.warning.call_count, 1)
        self.assertEqual(
            client._matrix_metrics["matrix.media.rejected.decrypt_failed"], 1  # pylint: disable=protected-access
        )

    async def test_cb_sync_response_persists_next_batch_token(self) -> None:
        client = self._client()
        response = SimpleNamespace(next_batch="next-token")

        await client._cb_sync_response(response)

        client._keyval_storage_gateway.put_text.assert_awaited_once_with(
            client._sync_key,
            "next-token",
        )
        self.assertEqual(client.sync_token, "next-token")
