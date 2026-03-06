"""Unit tests for mugen.core.plugin.wechat.ipc_ext."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.service.ingress_routing import (
    IngressRouteReason,
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.plugin.wechat import ipc_ext
from mugen.core.plugin.wechat.ipc_ext import WeChatIPCExtension


def _make_config(*, typing_enabled: bool = True, dedupe_ttl: int = 86400) -> SimpleNamespace:
    return SimpleNamespace(
        wechat=SimpleNamespace(
            webhook=SimpleNamespace(dedupe_ttl_seconds=dedupe_ttl),
            typing=SimpleNamespace(enabled=typing_enabled),
        )
    )


def _make_request(
    data: dict,
    command: str = "wechat_official_account_event",
    path_token: str = "wechat-path-token",
) -> IPCCommandRequest:
    payload = dict(data)
    payload.setdefault("path_token", path_token)
    return IPCCommandRequest(
        platform="wechat",
        command=command,
        data=payload,
    )


def _make_messaging_service():
    return SimpleNamespace(
        handle_audio_message=AsyncMock(return_value=[]),
        handle_file_message=AsyncMock(return_value=[]),
        handle_image_message=AsyncMock(return_value=[]),
        handle_text_message=AsyncMock(return_value=[]),
        handle_video_message=AsyncMock(return_value=[]),
        mh_extensions=[],
    )


def _make_client():
    return SimpleNamespace(
        send_audio_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_file_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_image_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_text_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_video_message=AsyncMock(return_value={"ok": True, "data": {}}),
        send_raw_message=AsyncMock(return_value={"ok": True, "data": {}}),
        emit_processing_signal=AsyncMock(return_value=True),
        download_media=AsyncMock(
            return_value={
                "path": "/tmp/file.bin",
                "mime_type": "application/octet-stream",
                "size": 2,
            }
        ),
        upload_media=AsyncMock(return_value={"ok": True, "data": {"media_id": "m-1"}}),
    )


def _make_user_service(known_users=None):
    return SimpleNamespace(
        get_known_users_list=AsyncMock(return_value=dict(known_users or {})),
        add_known_user=AsyncMock(),
    )


class _MemoryRelational:
    def __init__(self):
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict) -> dict:
        if table == "wechat_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "wechat_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict) -> dict | None:
        if table != "wechat_event_dedup":
            raise ValueError(f"Unsupported table: {table}")
        key = (where.get("event_type"), where.get("dedupe_key"))
        existing = self.event_dedup.get(key)
        if existing is None:
            return None
        existing.update(changes)
        return dict(existing)


class _IngressRoutingStub:
    async def resolve(self, request) -> IngressRouteResolution:
        identifier_value = request.identifier_value
        if not isinstance(identifier_value, str) or identifier_value.strip() == "":
            identifier_value = "wechat-path-token"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="wechat",
                channel_key="wechat",
                identifier_claims={
                    "identifier_type": "path_token",
                    "identifier_value": str(identifier_value),
                },
            ),
        )


def _new_extension(
    *,
    config,
    client=None,
    relational_storage_gateway=None,
    messaging_service=None,
    user_service=None,
    logging_gateway=None,
    ingress_routing_service=None,
) -> WeChatIPCExtension:
    return WeChatIPCExtension(
        config=config,
        logging_gateway=logging_gateway or Mock(),
        relational_storage_gateway=(
            relational_storage_gateway or _MemoryRelational()
        ),
        messaging_service=messaging_service or _make_messaging_service(),
        user_service=user_service or _make_user_service(),
        wechat_client=client or _make_client(),
        ingress_routing_service=ingress_routing_service or _IngressRoutingStub(),
    )


def _make_text_payload(*, text: str = "hello") -> dict:
    return {
        "FromUserName": "user-1",
        "MsgType": "text",
        "Content": text,
        "MsgId": "msg-1",
    }


def _make_media_payload(*, msg_type: str) -> dict:
    payload = {
        "FromUserName": "user-1",
        "MsgType": msg_type,
        "MsgId": "msg-2",
        "MediaId": "media-1",
    }
    return payload


class TestMugenWeChatIpcExt(unittest.IsolatedAsyncioTestCase):
    """Covers event routing, media processing, and reliability behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            wechat_client="client",
            config="config",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
            messaging_service="ms",
            user_service="us",
        )
        with patch.object(ipc_ext.di, "container", new=container):
            self.assertEqual(ipc_ext._wechat_client_provider(), "client")
            self.assertEqual(ipc_ext._config_provider(), "config")
            self.assertEqual(ipc_ext._logging_gateway_provider(), "logger")
            self.assertEqual(ipc_ext._relational_storage_gateway_provider(), "rsg")
            self.assertEqual(ipc_ext._messaging_service_provider(), "ms")
            self.assertEqual(ipc_ext._user_service_provider(), "us")

    async def test_properties_and_process_command_dispatch(self) -> None:
        ext = _new_extension(config=_make_config())

        self.assertEqual(ext.platforms, ["wechat"])
        self.assertEqual(
            ext.ipc_commands,
            ["wechat_official_account_event", "wechat_wecom_event"],
        )

        with patch.object(ext, "_wechat_event", new=AsyncMock()) as event_handler:
            handled_oa = await ext.process_ipc_command(
                _make_request(
                    {"provider": "official_account", "payload": _make_text_payload()},
                    command="wechat_official_account_event",
                )
            )
            handled_wecom = await ext.process_ipc_command(
                _make_request(
                    {"provider": "wecom", "payload": _make_text_payload()},
                    command="wechat_wecom_event",
                )
            )
            unknown = await ext.process_ipc_command(
                _make_request({}, command="unknown")
            )

        self.assertEqual(event_handler.await_count, 2)
        self.assertTrue(handled_oa.ok)
        self.assertTrue(handled_wecom.ok)
        self.assertEqual(handled_oa.response, {"response": "OK"})
        self.assertEqual(handled_wecom.response, {"response": "OK"})
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.code, "not_found")

    async def test_text_message_routes_and_registers_user(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[{"type": "text", "content": "reply"}]
        )
        user_service = _make_user_service(known_users={})
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            user_service=user_service,
        )

        await ext._process_inbound_message(  # pylint: disable=protected-access
            provider="official_account",
            payload=_make_text_payload(),
        )

        messaging_service.handle_text_message.assert_awaited_once()
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "user-1")
        self.assertEqual(kwargs["sender"], "user-1")
        self.assertEqual(kwargs["message"], "hello")
        self.assertIsInstance(kwargs.get("message_context"), list)
        self.assertEqual(kwargs["message_context"][-1]["type"], "ingress_route")
        user_service.add_known_user.assert_awaited_once_with("user-1", "user-1", "user-1")
        client.send_text_message.assert_awaited_once_with(
            recipient="user-1",
            text="reply",
        )
        client.emit_processing_signal.assert_any_await(
            "user-1",
            state="start",
            message_id="msg-1",
        )
        client.emit_processing_signal.assert_any_await(
            "user-1",
            state="stop",
            message_id="msg-1",
        )

    async def test_media_messages_route_to_matching_handlers(self) -> None:
        cases = [
            ("voice", "handle_audio_message"),
            ("image", "handle_image_message"),
            ("video", "handle_video_message"),
            ("shortvideo", "handle_video_message"),
            ("file", "handle_file_message"),
        ]

        for msg_type, handler_name in cases:
            with self.subTest(msg_type=msg_type):
                client = _make_client()
                messaging_service = _make_messaging_service()
                ext = _new_extension(
                    config=_make_config(),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=_make_user_service(known_users={"user-1": "User One"}),
                )

                await ext._process_inbound_message(  # pylint: disable=protected-access
                    provider="official_account",
                    payload=_make_media_payload(msg_type=msg_type),
                )

                client.download_media.assert_awaited()
                getattr(messaging_service, handler_name).assert_awaited_once()

    async def test_duplicate_event_is_ignored(self) -> None:
        logger = Mock()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"user-1": "User One"}),
        )
        payload = _make_text_payload()

        await ext._process_inbound_message(  # pylint: disable=protected-access
            provider="official_account",
            payload=payload,
        )
        await ext._process_inbound_message(  # pylint: disable=protected-access
            provider="official_account",
            payload=payload,
        )

        messaging_service.handle_text_message.assert_awaited_once()
        logger.debug.assert_any_call("Skip duplicate WeChat event.")

    async def test_send_response_supports_generic_and_wechat_envelopes(self) -> None:
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client)

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": "hello"},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "wechat", "op": "send_message", "text": "native"},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "wechat",
                "op": "send_raw",
                "content": {"msgtype": "text", "text": {"content": "raw"}},
            },
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "audio",
                "file": {"uri": "/tmp/demo.ogg", "type": "voice"},
            },
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "file",
                "file": {"uri": "/tmp/demo.txt", "type": "file"},
            },
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "image",
                "file": {"uri": "/tmp/demo.png", "type": "image"},
            },
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "video",
                "file": {"uri": "/tmp/demo.mp4", "type": "video"},
            },
            "user-1",
        )

        client.send_text_message.assert_awaited()
        client.send_raw_message.assert_awaited_once()
        client.send_audio_message.assert_awaited_once()
        client.send_file_message.assert_awaited_once()
        client.send_image_message.assert_awaited_once()
        client.send_video_message.assert_awaited_once()

    async def test_send_response_logs_invalid_payload_shapes(self) -> None:
        logger = Mock()
        client = _make_client()
        client.upload_media = AsyncMock(return_value={"ok": True, "data": {}})
        ext = _new_extension(config=_make_config(), client=client, logging_gateway=logger)

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "wechat", "op": "send_raw", "content": []},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "wechat", "op": "send_message"},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "wechat", "op": "unknown"},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "audio", "file": {"uri": "/tmp/demo.ogg", "type": "voice"}},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "unknown"},
            "user-1",
        )

        logger.error.assert_any_call("Missing WeChat raw payload.")
        logger.error.assert_any_call("Missing WeChat send_message text payload.")
        logger.error.assert_any_call("Unsupported WeChat response op: unknown.")
        logger.error.assert_any_call("audio upload did not return media id.")
        logger.error.assert_any_call("Unsupported response type: unknown.")

    async def test_upload_response_media_prefers_media_id_and_validates_payload(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client, logging_gateway=logger)

        direct = await ext._upload_response_media(  # pylint: disable=protected-access
            {"file": {"id": "media-123"}},
            "audio",
        )
        self.assertEqual(direct["media_id"], "media-123")

        missing_file = await ext._upload_response_media(  # pylint: disable=protected-access
            {},
            "audio",
        )
        self.assertIsNone(missing_file)

        invalid_file = await ext._upload_response_media(  # pylint: disable=protected-access
            {"file": {"uri": "", "type": ""}},
            "audio",
        )
        self.assertIsNone(invalid_file)

    async def test_wechat_event_records_dead_letters_for_malformed_and_exceptions(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            relational_storage_gateway=relational,
        )

        await ext._wechat_event(  # pylint: disable=protected-access
            _make_request(
                {"provider": "official_account", "payload": []},
                command="wechat_official_account_event",
            ),
            expected_provider="official_account",
        )

        with patch.object(
            ext,
            "_process_inbound_message",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await ext._wechat_event(  # pylint: disable=protected-access
                _make_request(
                    {"provider": "official_account", "payload": _make_text_payload()},
                    command="wechat_official_account_event",
                ),
                expected_provider="official_account",
            )

        self.assertEqual(len(relational.dead_letters), 2)
        self.assertEqual(relational.dead_letters[0]["reason_code"], "malformed_payload")
        self.assertEqual(relational.dead_letters[1]["reason_code"], "processing_exception")
        logger.error.assert_any_call("Malformed WeChat event payload.")

    async def test_dedupe_and_dead_letter_storage_failures_are_logged(self) -> None:
        logger = Mock()
        relational = Mock()
        relational.insert_one = AsyncMock(side_effect=SQLAlchemyError("db-down"))
        relational.update_one = AsyncMock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            relational_storage_gateway=relational,
        )

        is_duplicate = await ext._is_duplicate_event(  # pylint: disable=protected-access
            "official_account:event",
            _make_text_payload(),
        )
        self.assertFalse(is_duplicate)

        await ext._record_dead_letter(  # pylint: disable=protected-access
            event_type="official_account:webhook",
            event_payload={"x": 1},
            reason_code="boom",
        )
        logger.error.assert_any_call(
            "WeChat dedupe lookup failed. error=SQLAlchemyError: db-down"
        )
        logger.error.assert_any_call(
            "Failed to write WeChat dead-letter event. reason_code=boom error=SQLAlchemyError: db-down"
        )

    async def test_invalid_config_branches_for_ttl_and_typing(self) -> None:
        ext_invalid = _new_extension(
            config=_make_config(typing_enabled=True, dedupe_ttl=-1),
        )
        self.assertEqual(ext_invalid._event_dedup_ttl_seconds, 86400)  # pylint: disable=protected-access
        self.assertTrue(ext_invalid._typing_enabled)  # pylint: disable=protected-access

        cfg = _make_config()
        cfg.wechat.typing.enabled = "off"
        ext_off = _new_extension(config=cfg)
        self.assertFalse(ext_off._typing_enabled)  # pylint: disable=protected-access

    async def test_ttl_parse_fallback_and_non_dict_dedupe_payload(self) -> None:
        cfg = _make_config()
        cfg.wechat.webhook.dedupe_ttl_seconds = "invalid"
        ext = _new_extension(config=cfg)
        self.assertEqual(ext._event_dedup_ttl_seconds, 86400)  # pylint: disable=protected-access

        dedupe_key = ext._build_event_dedupe_key("official_account:event", ["x"])  # type: ignore[arg-type]  # pylint: disable=protected-access
        self.assertTrue(dedupe_key.startswith("official_account:event:"))

    async def test_is_duplicate_event_integrity_update_error_branch(self) -> None:
        relational = Mock()
        relational.insert_one = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup")))
        relational.update_one = AsyncMock(side_effect=SQLAlchemyError("update-down"))
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
        )

        duplicate = await ext._is_duplicate_event(  # pylint: disable=protected-access
            "official_account:event",
            {"MsgId": "m-1"},
        )
        self.assertTrue(duplicate)

    async def test_is_duplicate_event_event_id_selection_branches(self) -> None:
        ext = _new_extension(config=_make_config(), relational_storage_gateway=_MemoryRelational())

        inserted_with_event_id = await ext._is_duplicate_event(  # pylint: disable=protected-access
            "official_account:event",
            {"event_id": 123},
        )
        inserted_with_no_ids = await ext._is_duplicate_event(  # pylint: disable=protected-access
            "official_account:event",
            {"FromUserName": "user-1"},
        )
        self.assertFalse(inserted_with_event_id)
        self.assertFalse(inserted_with_no_ids)

    async def test_emit_processing_signal_guard_and_exception_paths(self) -> None:
        logger = Mock()
        client_disabled = _make_client()
        ext_disabled = _new_extension(
            config=_make_config(typing_enabled=False),
            client=client_disabled,
            logging_gateway=logger,
        )
        await ext_disabled._emit_processing_signal(  # pylint: disable=protected-access
            recipient="user-1",
            message_id="msg-1",
            state="start",
        )
        client_disabled.emit_processing_signal.assert_not_awaited()

        client_not_callable = _make_client()
        client_not_callable.emit_processing_signal = None
        ext_not_callable = _new_extension(
            config=_make_config(),
            client=client_not_callable,
            logging_gateway=logger,
        )
        await ext_not_callable._emit_processing_signal(  # pylint: disable=protected-access
            recipient="user-1",
            message_id="msg-1",
            state="start",
        )

        client_error = _make_client()
        client_error.emit_processing_signal = AsyncMock(side_effect=RuntimeError("boom"))
        ext_error = _new_extension(
            config=_make_config(),
            client=client_error,
            logging_gateway=logger,
        )
        await ext_error._emit_processing_signal(  # pylint: disable=protected-access
            recipient="user-1",
            message_id="msg-1",
            state="start",
        )
        logger.warning.assert_called()

    async def test_download_and_upload_media_shape_failures(self) -> None:
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client, logging_gateway=Mock())

        client.download_media = AsyncMock(return_value=None)
        self.assertIsNone(
            await ext._download_message_media(media_id="m-0")  # pylint: disable=protected-access
        )

        client.download_media = AsyncMock(return_value={"path": "", "mime_type": "audio/ogg"})
        self.assertIsNone(
            await ext._download_message_media(media_id="m-1")  # pylint: disable=protected-access
        )

        client.download_media = AsyncMock(return_value={"mime_type": "audio/ogg"})
        self.assertIsNone(
            await ext._download_message_media(media_id="m-2")  # pylint: disable=protected-access
        )

        client.upload_media = AsyncMock(return_value=None)
        self.assertIsNone(
            await ext._upload_response_media(  # pylint: disable=protected-access
                {"file": {"uri": "/tmp/a.ogg", "type": "voice"}},
                "audio",
            )
        )

        client.upload_media = AsyncMock(return_value={"ok": True, "data": []})
        self.assertIsNone(
            await ext._upload_response_media(  # pylint: disable=protected-access
                {"file": {"uri": "/tmp/a.ogg", "type": "voice"}},
                "audio",
            )
        )

    async def test_send_response_invalid_generic_shapes(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client, logging_gateway=logger)

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": None},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "file", "file": {"uri": "", "type": ""}},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "image", "file": {"uri": "", "type": ""}},
            "user-1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "video", "file": {"uri": "", "type": ""}},
            "user-1",
        )

        logger.error.assert_any_call("Missing text content in response payload.")
        logger.error.assert_any_call("Invalid file payload for file response.")
        logger.error.assert_any_call("Invalid file payload for image response.")
        logger.error.assert_any_call("Invalid file payload for video response.")

    async def test_process_inbound_message_missing_fields_and_unsupported_types(self) -> None:
        logger = Mock()
        client = _make_client()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"user-1": "User One"}),
            logging_gateway=logger,
        )

        await ext._process_inbound_message(  # pylint: disable=protected-access
            provider="official_account",
            payload={"MsgType": "text", "MsgId": "1"},
        )
        logger.error.assert_any_call("Malformed WeChat event payload.")

        await ext._process_inbound_message(  # pylint: disable=protected-access
            provider="official_account",
            payload={
                "FromUserName": "user-1",
                "MsgType": "text",
                "MsgId": "2",
            },
        )
        messaging_service.handle_text_message.assert_not_awaited()

        for msg_type in ["voice", "image", "video", "file"]:
            await ext._process_inbound_message(  # pylint: disable=protected-access
                provider="official_account",
                payload={
                    "FromUserName": "user-1",
                    "MsgType": msg_type,
                    "MsgId": f"id-{msg_type}",
                },
            )

        client.download_media = AsyncMock(return_value=None)
        for msg_type in ["voice", "image", "video", "file"]:
            await ext._process_inbound_message(  # pylint: disable=protected-access
                provider="official_account",
                payload={
                    "FromUserName": "user-1",
                    "MsgType": msg_type,
                    "MsgId": f"id-none-{msg_type}",
                    "MediaId": "missing-media",
                },
            )

        await ext._process_inbound_message(  # pylint: disable=protected-access
            provider="official_account",
            payload={
                "FromUserName": "user-1",
                "MsgType": "location",
                "MsgId": "id-location",
            },
        )
        logger.debug.assert_any_call("Unsupported WeChat message type: location.")

    async def test_wechat_event_invalid_request_shapes_and_provider_mismatch(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            relational_storage_gateway=relational,
        )

        await ext._wechat_event(  # pylint: disable=protected-access
            IPCCommandRequest(
                platform="wechat",
                command="wechat_official_account_event",
                data=[],  # type: ignore[arg-type]
            ),
            expected_provider="official_account",
        )

        await ext._wechat_event(  # pylint: disable=protected-access
            _make_request(
                {"provider": "wecom", "payload": _make_text_payload()},
                command="wechat_official_account_event",
            ),
            expected_provider="official_account",
        )

        self.assertEqual(len(relational.dead_letters), 2)
        self.assertEqual(relational.dead_letters[0]["reason_code"], "malformed_payload")
        self.assertEqual(relational.dead_letters[1]["reason_code"], "processing_exception")

    async def test_ingress_router_default_and_helper_fallback_branches(self) -> None:
        ext = WeChatIPCExtension(
            config=_make_config(),
            logging_gateway=Mock(),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=_make_messaging_service(),
            user_service=_make_user_service(),
            wechat_client=_make_client(),
            ingress_routing_service=None,
        )
        sentinel_router = object()
        with patch.object(
            ipc_ext,
            "DefaultIngressRoutingService",
            return_value=sentinel_router,
        ) as router_ctor:
            self.assertIs(ext._ingress_router(), sentinel_router)  # pylint: disable=protected-access
            self.assertIs(ext._ingress_router(), sentinel_router)  # pylint: disable=protected-access
            router_ctor.assert_called_once()

        self.assertEqual(  # pylint: disable=protected-access
            ext._compose_message_context(
                ingress_route={"tenant_slug": "tenant-a"},
                extra_context=["bad"],
            ),
            [
                {
                    "type": "ingress_route",
                    "content": {"tenant_slug": "tenant-a"},
                }
            ],
        )
        self.assertEqual(  # pylint: disable=protected-access
            ext._normalize_ingress_route(None)["platform"],
            "wechat",
        )
        merged = ext._merge_ingress_metadata(  # pylint: disable=protected-access
            payload={"metadata": []},
            ingress_route={"tenant_slug": "tenant-a"},
        )
        self.assertEqual(merged["metadata"]["ingress_route"]["tenant_slug"], "tenant-a")

    async def test_unresolved_ingress_route_is_dead_lettered_and_dropped(self) -> None:
        class _UnresolvedRouter:
            async def resolve(self, request):  # noqa: ARG002
                return IngressRouteResolution(
                    ok=False,
                    reason_code=IngressRouteReason.MISSING_BINDING.value,
                    reason_detail=None,
                )

        logger = Mock()
        relational = _MemoryRelational()
        messaging = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            relational_storage_gateway=relational,
            messaging_service=messaging,
            ingress_routing_service=_UnresolvedRouter(),
        )

        await ext._wechat_event(  # pylint: disable=protected-access
            _make_request(
                {"provider": "official_account", "payload": _make_text_payload()},
                command="wechat_official_account_event",
            ),
            expected_provider="official_account",
        )
        messaging.handle_text_message.assert_not_awaited()
        self.assertEqual(relational.dead_letters[0]["reason_code"], "route_unresolved")
        logger.warning.assert_called()

        class _UnresolvedWithDetailRouter:
            async def resolve(self, request):  # noqa: ARG002
                return IngressRouteResolution(
                    ok=False,
                    reason_code=IngressRouteReason.MISSING_BINDING.value,
                    reason_detail="detail",
                )

        ext_with_detail = _new_extension(
            config=_make_config(),
            logging_gateway=Mock(),
            relational_storage_gateway=_MemoryRelational(),
            ingress_routing_service=_UnresolvedWithDetailRouter(),
        )
        await ext_with_detail._resolve_ingress_route(  # pylint: disable=protected-access
            path_token="wechat-path-token",
            webhook_payload={"event": "x"},
        )
        self.assertIn(
            "detail",
            str(ext_with_detail._relational_storage_gateway.dead_letters[0]["error_message"]),  # pylint: disable=protected-access
        )
