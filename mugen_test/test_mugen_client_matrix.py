"""Unit tests for matrix DefaultMatrixClient utility and branch behavior."""

from io import BytesIO
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from nio import LocalProtocolError

from mugen.core.client import matrix as matrix_mod
from mugen.core.client.matrix import DefaultMatrixClient


class _DeviceStore(dict):
    def active_user_devices(self, user_id: str) -> list[SimpleNamespace]:
        devices = self.get(user_id, {})
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
                matrix_mod.IMatrixClient, "__init__", autospec=True, return_value=None
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

        base_init.assert_called_once_with(
            client,
            homeserver="https://matrix.example.com",
            user="@assistant:example.com",
            store_path="/tmp/olm",
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
        client._messaging_service = Mock()
        client._user_service = Mock()
        client._ipc_service = Mock()
        client.user_id = "@assistant:example.com"
        client.login = AsyncMock()
        client.load_store = Mock()
        client.get_profile = AsyncMock()
        client.room_leave = AsyncMock()
        client.join = AsyncMock()
        client.room_put_state = AsyncMock()
        client.room_get_state = AsyncMock()
        client.room_read_markers = AsyncMock()
        client.room_send = AsyncMock()
        client.upload = AsyncMock()
        client.download = AsyncMock()
        client.verify_device = Mock()
        client.device_store = _DeviceStore()
        client.client_session = SimpleNamespace(close=AsyncMock())
        return client

    async def test_aenter_uses_saved_credentials_when_access_token_exists(self) -> None:
        client = self._client()

        values = {
            "client_access_token": "tok",
            "client_device_id": "dev",
            "client_user_id": "@assistant:example.com",
        }
        client._keyval_storage_gateway.get = Mock(
            side_effect=lambda key, *_: values[key]
        )

        result = await client.__aenter__()

        self.assertIs(result, client)
        self.assertEqual(client.access_token, "tok")
        self.assertEqual(client.device_id, "dev")
        self.assertEqual(client.user_id, "@assistant:example.com")
        client.load_store.assert_called_once_with()

    async def test_aenter_password_login_success_saves_credentials(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get = Mock(return_value=None)
        client.login = AsyncMock(
            return_value=_FakeLoginResponse("access", "device-1", "@user:example.com")
        )

        with patch.object(matrix_mod, "LoginResponse", _FakeLoginResponse):
            result = await client.__aenter__()

        self.assertIs(result, client)
        self.assertEqual(client._keyval_storage_gateway.put.call_count, 3)
        client.load_store.assert_called_once_with()

    async def test_aenter_password_login_failure_raises_runtime_error(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get = Mock(return_value=None)
        client.login = AsyncMock(return_value=object())

        with (
            patch.object(matrix_mod, "LoginResponse", _FakeLoginResponse),
            self.assertRaisesRegex(RuntimeError, "Matrix password login failed"),
        ):
            await client.__aenter__()

    async def test_aexit_closes_client_session_and_handles_missing_session(
        self,
    ) -> None:
        client = self._client()
        await client.__aexit__(None, None, None)
        client.client_session.close.assert_awaited_once_with()

        del client.client_session
        await client.__aexit__(None, None, None)

    async def test_sync_token_property_reads_storage(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.get = Mock(return_value="next-batch")
        self.assertEqual(client.sync_token, "next-batch")

    async def test_cleanup_and_trust_known_user_devices_list(self) -> None:
        client = self._client()
        known_devices = {"@user:example.com": ["DEV-1"]}
        client._keyval_storage_gateway.has_key = Mock(return_value=True)
        client._keyval_storage_gateway.get = Mock(
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

        client.cleanup_known_user_devices_list()

        persisted = json.loads(client._keyval_storage_gateway.put.call_args.args[1])
        self.assertEqual(persisted["@user:example.com"], ["DEV-1", "DEV-2"])

        client.verify_device = Mock()
        client.trust_known_user_devices()
        self.assertEqual(client.verify_device.call_count, 1)

    async def test_cleanup_and_trust_known_user_devices_no_stored_key(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.has_key = Mock(return_value=False)

        client.cleanup_known_user_devices_list()
        client.trust_known_user_devices()

        client._keyval_storage_gateway.put.assert_not_called()
        client.verify_device.assert_not_called()

    async def test_known_devices_invalid_payload_is_ignored(self) -> None:
        client = self._client()
        client._keyval_storage_gateway.has_key = Mock(return_value=True)
        client._keyval_storage_gateway.get = Mock(return_value="{")

        client.cleanup_known_user_devices_list()
        client.trust_known_user_devices()

        client._keyval_storage_gateway.put.assert_not_called()
        client.verify_device.assert_not_called()
        self.assertGreaterEqual(client._logging_gateway.warning.call_count, 1)

    async def test_load_known_devices_handles_bytes_type_mismatch_and_value_filtering(
        self,
    ) -> None:
        client = self._client()
        client._keyval_storage_gateway.has_key = Mock(return_value=True)

        client._keyval_storage_gateway.get = Mock(return_value=b"\xff")
        self.assertEqual(
            client._load_known_devices(), {}
        )  # pylint: disable=protected-access

        client._keyval_storage_gateway.get = Mock(
            return_value=json.dumps(["not-a-dict"])
        )
        self.assertEqual(
            client._load_known_devices(), {}
        )  # pylint: disable=protected-access

        client._keyval_storage_gateway.get = Mock(
            return_value=json.dumps(
                {
                    "@user:example.com": "DEV-1",
                    "@other:example.com": ["DEV-2", 3],
                }
            )
        )
        self.assertEqual(
            client._load_known_devices(),  # pylint: disable=protected-access
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
        client._keyval_storage_gateway.has_key = Mock(return_value=False)

        client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 2)
        self.assertEqual(client._keyval_storage_gateway.put.call_count, 2)

        known = {"@user:example.com": ["DEV-1", "DEV-2"]}
        client.verify_device.reset_mock()
        client._keyval_storage_gateway.put.reset_mock()
        client._keyval_storage_gateway.has_key = Mock(return_value=True)
        client._keyval_storage_gateway.get = Mock(return_value=json.dumps(known))

        client.verify_user_devices("@user:example.com")

        client.verify_device.assert_not_called()
        client._keyval_storage_gateway.put.assert_not_called()

    async def test_verify_user_devices_strict_known_only_verifies_known_devices(
        self,
    ) -> None:
        client = self._client()
        client._config.matrix.security.device_trust.mode = "strict_known"
        client.device_store = _DeviceStore(
            {"@user:example.com": {"DEV-1": object(), "DEV-2": object()}}
        )
        client._keyval_storage_gateway.has_key = Mock(return_value=True)
        client._keyval_storage_gateway.get = Mock(
            return_value=json.dumps({"@user:example.com": ["DEV-1"]})
        )

        client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 1)
        client._keyval_storage_gateway.put.assert_not_called()
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
        client._keyval_storage_gateway.has_key = Mock(return_value=False)

        client.verify_user_devices("@user:example.com")

        self.assertEqual(client.verify_device.call_count, 1)
        client._keyval_storage_gateway.put.assert_not_called()
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

        client.room_get_state = AsyncMock(
            return_value=SimpleNamespace(
                events=[
                    {"type": client._flags_key, "content": {"m.direct": 1}},
                ]
            )
        )
        self.assertTrue(await client._is_direct_message(room.room_id))

        client.room_get_state = AsyncMock(return_value=SimpleNamespace(events=[]))
        self.assertFalse(await client._is_direct_message(room.room_id))

        client._is_direct_message = AsyncMock(return_value=True)
        own_message = SimpleNamespace(sender=client.user_id, event_id="$e1")
        self.assertFalse(await client._validate_message(room, own_message))

        client._is_direct_message = AsyncMock(return_value=False)
        not_direct = SimpleNamespace(sender="@user:example.com", event_id="$e2")
        self.assertFalse(await client._validate_message(room, not_direct))

        client._is_direct_message = AsyncMock(return_value=True)
        client.verify_user_devices = Mock()
        valid_message = SimpleNamespace(sender="@user:example.com", event_id="$e3")
        self.assertTrue(await client._validate_message(room, valid_message))
        client.verify_user_devices.assert_called_with("@user:example.com")
        client.room_read_markers.assert_awaited_with("!room:test", "$e3", "$e3")

        malformed_sender = SimpleNamespace(sender="invalid-user-id", event_id="$e4")
        self.assertFalse(await client._validate_message(room, malformed_sender))
        self.assertIn(
            "Reason: Malformed sender.",
            client._logging_gateway.warning.call_args.args[0],
        )

    async def test_is_direct_message_handles_malformed_room_state_payload(self) -> None:
        client = self._client()

        client.room_get_state = AsyncMock(return_value=SimpleNamespace(events="invalid"))
        self.assertFalse(await client._is_direct_message("!room:test"))

        client.room_get_state = AsyncMock(
            return_value=SimpleNamespace(
                events=[
                    "not-a-dict",
                    {"type": "m.other", "content": {"m.direct": 1}},
                    {"type": client._flags_key, "content": {"m.direct": 0}},
                ]
            )
        )
        self.assertFalse(await client._is_direct_message("!room:test"))

        client.room_get_state = AsyncMock(
            return_value=SimpleNamespace(
                events=[
                    {"type": client._flags_key, "content": "invalid"},
                    {"type": client._flags_key, "content": {"m.direct": True}},
                ]
            )
        )
        self.assertTrue(await client._is_direct_message("!room:test"))

    async def test_cb_invite_member_event_reject_and_accept_paths(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client.verify_user_devices = Mock()

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
        with patch.object(matrix_mod, "ProfileGetResponse", _FakeProfileGetResponse):
            await client._cb_invite_member_event(room, event)

        client.join.assert_awaited_once_with("!room:test")
        client.room_put_state.assert_awaited_once()
        client._user_service.add_known_user.assert_called_once_with(
            "@u:example.com",
            "User",
            "!room:test",
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
        client.verify_user_devices = Mock()
        client.get_profile = AsyncMock(return_value=_FakeProfileGetResponse("User"))
        event = SimpleNamespace(content={"membership": "invite"}, sender="@u:example.com")

        with patch.object(matrix_mod, "ProfileGetResponse", _FakeProfileGetResponse):
            await client._cb_invite_member_event(room, event)

        client.room_leave.assert_not_called()
        client.join.assert_awaited_once_with("!room:test")

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
        client.verify_user_devices = Mock()
        client.get_profile = AsyncMock(return_value=object())
        event = SimpleNamespace(
            content={"membership": "invite", "is_direct": True},
            sender="@beta:example.com",
        )

        with patch.object(matrix_mod, "ProfileGetResponse", _FakeProfileGetResponse):
            await client._cb_invite_member_event(room, event)

        client.join.assert_awaited_once_with("!room:test")
        client.room_put_state.assert_awaited_once()
        client._user_service.add_known_user.assert_not_called()

    async def test_callback_skip_logging_for_stubbed_paths(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        callback_invocations = [
            ("_cb_megolm_event", (room, object())),
            ("_cb_invite_alias_event", (object(),)),
            ("_cb_invite_name_event", (room, object())),
            ("_cb_room_create_event", (room, object())),
            ("_cb_key_verification_event", (object(),)),
            ("_cb_room_key_event", (object(),)),
            ("_cb_room_key_request", (room, object())),
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

    async def test_cb_room_message_returns_early_when_validation_fails(self) -> None:
        client = self._client()
        room = SimpleNamespace(room_id="!room:test")
        client._validate_message = AsyncMock(return_value=False)
        client._process_message_responses = AsyncMock(return_value=None)

        with patch.object(matrix_mod, "RoomMessageText", _FakeTextMessage):
            await client._cb_room_message(room, _FakeTextMessage())

        client._process_message_responses.assert_not_called()

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

    async def test_cb_sync_response_persists_next_batch_token(self) -> None:
        client = self._client()
        response = SimpleNamespace(next_batch="next-token")

        await client._cb_sync_response(response)

        client._keyval_storage_gateway.put.assert_called_once_with(
            client._sync_key,
            "next-token",
        )
