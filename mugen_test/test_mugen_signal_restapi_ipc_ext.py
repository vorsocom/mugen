"""Unit tests for mugen.core.plugin.signal.restapi.ipc_ext."""

from __future__ import annotations

import base64
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.plugin.signal.restapi import ipc_ext
from mugen.core.plugin.signal.restapi.ipc_ext import SignalRestAPIIPCExtension


def _make_config(*, typing_enabled: bool = True, dedupe_ttl: int = 86400) -> SimpleNamespace:
    return SimpleNamespace(
        signal=SimpleNamespace(
            receive=SimpleNamespace(dedupe_ttl_seconds=dedupe_ttl),
            typing=SimpleNamespace(enabled=typing_enabled),
        )
    )


def _make_request(
    data: dict,
    command: str = "signal_restapi_event",
) -> IPCCommandRequest:
    return IPCCommandRequest(
        platform="signal",
        command=command,
        data=data,
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
        send_text_message=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        send_media_message=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        send_reaction=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        send_receipt=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        emit_processing_signal=AsyncMock(return_value=True),
        download_attachment=AsyncMock(
            return_value={
                "path": "/tmp/file.bin",
                "mime_type": "application/octet-stream",
            }
        ),
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
        if table == "signal_restapi_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "signal_restapi_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict) -> dict | None:
        if table != "signal_restapi_event_dedup":
            raise ValueError(f"Unsupported table: {table}")
        key = (where.get("event_type"), where.get("dedupe_key"))
        existing = self.event_dedup.get(key)
        if existing is None:
            return None
        existing.update(changes)
        return dict(existing)


class _DeadLetterFailingRelational(_MemoryRelational):
    async def insert_one(self, table: str, record: dict) -> dict:
        if table == "signal_restapi_event_dead_letter":
            raise SQLAlchemyError("dead-letter-down")
        return await super().insert_one(table, record)


class _DedupeErrorRelational(_MemoryRelational):
    async def insert_one(self, table: str, record: dict) -> dict:
        if table == "signal_restapi_event_dedup":
            raise SQLAlchemyError("dedupe-down")
        return await super().insert_one(table, record)


class _DedupeUpdateErrorRelational(_MemoryRelational):
    async def update_one(self, table: str, where: dict, changes: dict) -> dict | None:
        raise SQLAlchemyError("update-down")


def _new_extension(
    *,
    config,
    client=None,
    relational_storage_gateway=None,
    messaging_service=None,
    user_service=None,
    logging_gateway=None,
) -> SignalRestAPIIPCExtension:
    return SignalRestAPIIPCExtension(
        config=config,
        logging_gateway=logging_gateway or Mock(),
        relational_storage_gateway=(
            relational_storage_gateway or _MemoryRelational()
        ),
        messaging_service=messaging_service or _make_messaging_service(),
        user_service=user_service or _make_user_service(),
        signal_client=client or _make_client(),
    )


def _receive_payload(envelope: dict) -> dict:
    return {
        "method": "receive",
        "params": {
            "envelope": envelope,
        },
    }


def _text_envelope(*, text: str = "hello", group_id: str | None = None) -> dict:
    payload = {
        "sourceNumber": "+15550001",
        "sourceUuid": "src-uuid-1",
        "timestamp": 123,
        "dataMessage": {
            "message": text,
        },
    }
    if group_id is not None:
        payload["dataMessage"]["groupInfo"] = {"groupId": group_id}
    return payload


def _reaction_envelope(*, emoji: str = "👍") -> dict:
    return {
        "sourceNumber": "+15550001",
        "timestamp": 124,
        "dataMessage": {
            "reaction": {
                "emoji": emoji,
                "targetAuthor": "+15550002",
                "targetSentTimestamp": 120,
            }
        },
    }


class TestMugenSignalRestapiIpcExt(unittest.IsolatedAsyncioTestCase):
    """Covers Signal IPC event routing, outbound mapping, and reliability behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            signal_client="client",
            config="config",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
            messaging_service="ms",
            user_service="us",
        )
        with patch.object(ipc_ext.di, "container", new=container):
            self.assertEqual(ipc_ext._signal_client_provider(), "client")
            self.assertEqual(ipc_ext._config_provider(), "config")
            self.assertEqual(ipc_ext._logging_gateway_provider(), "logger")
            self.assertEqual(ipc_ext._relational_storage_gateway_provider(), "rsg")
            self.assertEqual(ipc_ext._messaging_service_provider(), "ms")
            self.assertEqual(ipc_ext._user_service_provider(), "us")

    async def test_properties_and_process_command_dispatch(self) -> None:
        ext = _new_extension(config=_make_config())

        self.assertEqual(ext.platforms, ["signal"])
        self.assertEqual(ext.ipc_commands, ["signal_restapi_event"])

        with patch.object(ext, "_signal_restapi_event", new=AsyncMock()) as event_handler:
            handled = await ext.process_ipc_command(
                _make_request({}, command="signal_restapi_event")
            )
            unknown = await ext.process_ipc_command(
                _make_request({}, command="unknown")
            )

        event_handler.assert_awaited_once()
        self.assertTrue(handled.ok)
        self.assertEqual(handled.response, {"response": "OK"})
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.code, "not_found")

    async def test_helper_parsers_and_classification(self) -> None:
        ext = _new_extension(config=_make_config(dedupe_ttl=-1))
        self.assertEqual(ext._event_dedup_ttl_seconds, 86400)  # pylint: disable=protected-access
        self.assertIn("message:", ext._build_event_dedupe_key("message", {"a": 1}))  # pylint: disable=protected-access

        ext_bad_ttl = _new_extension(config=_make_config(dedupe_ttl="bad"))  # type: ignore[arg-type]
        self.assertEqual(ext_bad_ttl._event_dedup_ttl_seconds, 86400)  # pylint: disable=protected-access

        self.assertIsNone(ext._extract_envelope("bad"))  # pylint: disable=protected-access
        self.assertIsNone(ext._extract_envelope({}))  # pylint: disable=protected-access
        self.assertIsNone(ext._extract_envelope({"method": "bad"}))  # pylint: disable=protected-access
        self.assertIsNone(ext._extract_envelope({"method": "receive", "params": []}))  # pylint: disable=protected-access
        self.assertIsNone(  # pylint: disable=protected-access
            ext._extract_envelope({"method": "receive", "params": {"envelope": "bad"}})
        )
        envelope = _text_envelope(text="hello")
        self.assertEqual(
            ext._extract_envelope(_receive_payload(envelope)),  # pylint: disable=protected-access
            envelope,
        )

        self.assertEqual(ext._extract_event_id({"timestamp": 1}), "1")  # pylint: disable=protected-access
        self.assertEqual(
            ext._extract_event_id({"timestamp": 1, "sourceUuid": "u1"}),  # pylint: disable=protected-access
            "u1:1",
        )
        self.assertEqual(
            ext._extract_event_id({"timestamp": 1, "sourceNumber": "+1"}),  # pylint: disable=protected-access
            "+1:1",
        )
        self.assertIsNone(ext._extract_event_id({"timestamp": "bad"}))  # pylint: disable=protected-access

        self.assertEqual(
            ext._extract_sender({"sourceNumber": "+1"}),  # pylint: disable=protected-access
            "+1",
        )
        self.assertEqual(
            ext._extract_sender({"sourceUuid": "u1"}),  # pylint: disable=protected-access
            "u1",
        )
        self.assertEqual(
            ext._extract_sender({"source": "legacy"}),  # pylint: disable=protected-access
            "legacy",
        )
        self.assertIsNone(ext._extract_sender({}))  # pylint: disable=protected-access

        self.assertEqual(
            ext._extract_room_id(_text_envelope(group_id="group-1"), "+1"),  # pylint: disable=protected-access
            "group-1",
        )
        self.assertEqual(ext._extract_room_id({}, "+1"), "+1")  # pylint: disable=protected-access
        self.assertEqual(
            ext._extract_room_id(_text_envelope(), "+1"),  # pylint: disable=protected-access
            "+1",
        )
        self.assertEqual(  # pylint: disable=protected-access
            ext._extract_room_id(_text_envelope(group_id="   "), "+1"),
            "+1",
        )
        self.assertEqual(ext._extract_text_message(_text_envelope(text="x")), "x")  # pylint: disable=protected-access
        self.assertIsNone(ext._extract_text_message({}))  # pylint: disable=protected-access
        self.assertIsNotNone(ext._extract_reaction(_reaction_envelope()))  # pylint: disable=protected-access
        self.assertIsNone(ext._extract_reaction(_reaction_envelope(emoji="")))  # pylint: disable=protected-access
        self.assertEqual(ext._extract_attachments({}), [])  # pylint: disable=protected-access
        self.assertEqual(ext._classify_event_type(_reaction_envelope()), "reaction")  # pylint: disable=protected-access
        self.assertEqual(ext._classify_event_type(_text_envelope()), "message")  # pylint: disable=protected-access
        self.assertEqual(
            ext._classify_event_type({"receiptMessage": {}}),  # pylint: disable=protected-access
            "receipt",
        )
        self.assertEqual(ext._classify_event_type({}), "unknown")  # pylint: disable=protected-access

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

        await ext._signal_restapi_event(  # pylint: disable=protected-access
            _make_request(_receive_payload(_text_envelope(text="hello")))
        )

        messaging_service.handle_text_message.assert_awaited_once_with(
            "signal",
            room_id="+15550001",
            sender="+15550001",
            message="hello",
            message_context=None,
        )
        user_service.add_known_user.assert_awaited_once_with(
            "+15550001",
            "+15550001",
            "+15550001",
        )
        client.send_text_message.assert_awaited_once_with(
            recipient="+15550001",
            text="reply",
        )
        client.emit_processing_signal.assert_any_await(
            "+15550001",
            state="start",
        )
        client.emit_processing_signal.assert_any_await(
            "+15550001",
            state="stop",
        )

    async def test_reaction_routes_as_text_with_context(self) -> None:
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"+15550001": "Known"}),
        )

        await ext._signal_restapi_event(  # pylint: disable=protected-access
            _make_request(_receive_payload(_reaction_envelope(emoji="🔥")))
        )

        messaging_service.handle_text_message.assert_awaited_once()
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["message"], "🔥")
        self.assertEqual(kwargs["message_context"][0]["type"], "signal_reaction")

    async def test_attachments_route_to_matching_handlers(self) -> None:
        cases = [
            ("audio/ogg", "handle_audio_message"),
            ("image/png", "handle_image_message"),
            ("video/mp4", "handle_video_message"),
            ("application/pdf", "handle_file_message"),
        ]

        for mime_type, handler_name in cases:
            with self.subTest(mime_type=mime_type):
                client = _make_client()
                client.download_attachment = AsyncMock(
                    return_value={"path": "/tmp/f", "mime_type": mime_type}
                )
                messaging_service = _make_messaging_service()
                ext = _new_extension(
                    config=_make_config(),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=_make_user_service(known_users={"+15550001": "Known"}),
                )
                envelope = _text_envelope(text="")
                envelope["dataMessage"]["attachments"] = [{"id": "att-1"}]

                await ext._signal_restapi_event(  # pylint: disable=protected-access
                    _make_request(_receive_payload(envelope))
                )

                getattr(messaging_service, handler_name).assert_awaited_once()

    async def test_send_response_to_user_branches(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "signal", "op": "send_message", "text": "hello"},
            "+1",
        )
        client.send_text_message.assert_awaited()

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "signal", "op": "send_message", "text": ""},
            "+1",
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "signal",
                "op": "send_reaction",
                "reaction": "👍",
                "target_author": "+2",
                "timestamp": 1,
            },
            "+1",
        )
        client.send_reaction.assert_awaited()

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "signal",
                "op": "send_reaction",
                "reaction": "",
                "target_author": "+2",
                "timestamp": 1,
            },
            "+1",
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "signal",
                "op": "send_receipt",
                "receipt_type": "read",
                "timestamp": 1,
            },
            "+1",
        )
        client.send_receipt.assert_awaited()

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "signal", "op": "send_receipt", "receipt_type": "", "timestamp": 1},
            "+1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "signal", "op": "unknown"},
            "+1",
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": "hello"},
            "+1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": ""},
            "+1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "image", "file": {"base64": "data:image/png;base64,aaaa"}},
            "+1",
        )
        client.send_media_message.assert_awaited()
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "image",
                "content": "caption",
                "file": {"base64": "data:image/png;base64,bbbb"},
            },
            "+1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "image", "file": {}},
            "+1",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "unsupported"},
            "+1",
        )

        self.assertTrue(
            any("Unsupported response type" in str(call.args[0]) for call in logger.error.call_args_list)
        )

    async def test_attachment_data_url_helper_paths(self) -> None:
        ext = _new_extension(config=_make_config())
        inline = ext._attachment_as_base64_data_url({"base64": "abc"})  # pylint: disable=protected-access
        self.assertEqual(inline, "abc")
        self.assertIsNone(ext._attachment_as_base64_data_url("bad"))  # type: ignore[arg-type]  # pylint: disable=protected-access

        self.assertIsNone(ext._attachment_as_base64_data_url({}))  # pylint: disable=protected-access
        self.assertIsNone(  # pylint: disable=protected-access
            ext._attachment_as_base64_data_url({"path": "/does/not/exist"})
        )

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            handle.write(b"hello")
            file_path = handle.name
        try:
            encoded = ext._attachment_as_base64_data_url(  # pylint: disable=protected-access
                {"path": file_path, "mime_type": "text/plain"}
            )
            self.assertTrue(encoded.startswith("data:text/plain;base64,"))
            payload = encoded.split(",", 1)[1]
            self.assertEqual(base64.b64decode(payload.encode("utf-8")), b"hello")

            encoded_default_mime = ext._attachment_as_base64_data_url(  # pylint: disable=protected-access
                {"path": file_path}
            )
            self.assertTrue(encoded_default_mime.startswith("data:application/octet-stream;base64,"))
        finally:
            Path(file_path).unlink(missing_ok=True)

    async def test_emit_processing_signal_guard_and_exception_paths(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )

        await ext._emit_processing_signal(  # pylint: disable=protected-access
            recipient="+1",
            message_id="m1",
            state="start",
        )
        client.emit_processing_signal.assert_awaited_once()

        client_no_emitter = _make_client()
        client_no_emitter.emit_processing_signal = None
        ext_no_emitter = _new_extension(
            config=_make_config(),
            client=client_no_emitter,
            logging_gateway=logger,
        )
        await ext_no_emitter._emit_processing_signal(  # pylint: disable=protected-access
            recipient="+1",
            message_id="m1",
            state="start",
        )

        client_fail = _make_client()
        client_fail.emit_processing_signal = AsyncMock(return_value=False)
        ext_fail = _new_extension(
            config=_make_config(),
            client=client_fail,
            logging_gateway=logger,
        )
        await ext_fail._emit_processing_signal(  # pylint: disable=protected-access
            recipient="+1",
            message_id="m1",
            state="start",
        )

        client_raise = _make_client()
        client_raise.emit_processing_signal = AsyncMock(side_effect=RuntimeError("boom"))
        ext_raise = _new_extension(
            config=_make_config(),
            client=client_raise,
            logging_gateway=logger,
        )
        await ext_raise._emit_processing_signal(  # pylint: disable=protected-access
            recipient="+1",
            message_id="m1",
            state="start",
        )

        self.assertTrue(
            any("thinking signal reported failure" in str(call.args[0]) for call in logger.warning.call_args_list)
        )
        self.assertTrue(
            any("thinking signal raised unexpectedly" in str(call.args[0]) for call in logger.warning.call_args_list)
        )

    async def test_dispatch_attachments_skips_invalid_and_download_failures(self) -> None:
        client = _make_client()
        client.download_attachment = AsyncMock(side_effect=[None, {"path": "/tmp/f", "mime_type": "application/pdf"}])
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
        )

        responses = await ext._dispatch_attachments(  # pylint: disable=protected-access
            sender="+1",
            room_id="+1",
            attachments=[{}, {"id": ""}, {"id": "a1"}, {"id": "a2"}],
        )
        self.assertEqual(responses, [])
        messaging_service.handle_file_message.assert_awaited_once()

    async def test_dispatch_attachments_handles_non_list_and_missing_mime(self) -> None:
        client = _make_client()
        client.download_attachment = AsyncMock(return_value={"path": "/tmp/f", "mime_type": None})
        messaging_service = _make_messaging_service()
        messaging_service.handle_file_message = AsyncMock(return_value={"type": "text"})
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
        )

        responses = await ext._dispatch_attachments(  # pylint: disable=protected-access
            sender="+1",
            room_id="+1",
            attachments=[{"id": "a1"}],
        )
        self.assertEqual(responses, [])
        messaging_service.handle_file_message.assert_awaited_once()

    async def test_handle_message_event_missing_sender_and_non_list_response_paths(self) -> None:
        logger = Mock()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(return_value={"type": "text"})
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={}),
        )

        await ext._handle_message_event({"timestamp": 1})  # pylint: disable=protected-access
        logger.error.assert_any_call("Signal event missing sender identity.")

        text_envelope = _text_envelope(text="hello")
        await ext._handle_message_event(text_envelope)  # pylint: disable=protected-access

        reaction_envelope = _reaction_envelope(emoji="👍")
        await ext._handle_message_event(reaction_envelope)  # pylint: disable=protected-access

        with patch.object(
            ext,
            "_extract_reaction",
            return_value={"emoji": "   "},
        ):
            await ext._handle_message_event(_reaction_envelope(emoji="👍"))  # pylint: disable=protected-access

    async def test_malformed_missing_duplicate_receipt_unknown_and_failure_paths(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
            logging_gateway=logger,
        )

        await ext._signal_restapi_event(  # pylint: disable=protected-access
            _make_request("bad")  # type: ignore[arg-type]
        )
        await ext._signal_restapi_event(  # pylint: disable=protected-access
            _make_request({})
        )
        self.assertEqual(len(relational.dead_letters), 2)
        self.assertEqual(relational.dead_letters[0]["reason_code"], "invalid_payload_type")
        self.assertEqual(relational.dead_letters[1]["reason_code"], "missing_envelope")

        payload = _receive_payload(_text_envelope(text="hello"))
        await ext._signal_restapi_event(_make_request(payload))  # first delivery
        await ext._signal_restapi_event(_make_request(payload))  # duplicate

        receipt_payload = _receive_payload({"sourceNumber": "+1", "timestamp": 2, "receiptMessage": {}})
        await ext._signal_restapi_event(_make_request(receipt_payload))
        logger.debug.assert_any_call("Signal receipt event observed.")

        unknown_payload = _receive_payload({"sourceNumber": "+1", "timestamp": 3})
        await ext._signal_restapi_event(_make_request(unknown_payload))
        logger.debug.assert_any_call("Signal event ignored (unsupported type).")

        messaging_fail = _make_messaging_service()
        messaging_fail.handle_text_message = AsyncMock(side_effect=RuntimeError("boom"))
        ext_fail = _new_extension(
            config=_make_config(),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=messaging_fail,
            user_service=_make_user_service(known_users={"+15550001": "Known"}),
        )
        with self.assertRaises(RuntimeError):
            await ext_fail._signal_restapi_event(  # pylint: disable=protected-access
                _make_request(_receive_payload(_text_envelope(text="hello")))
            )
        self.assertEqual(len(ext_fail._relational_storage_gateway.dead_letters), 1)  # pylint: disable=protected-access
        self.assertEqual(
            ext_fail._relational_storage_gateway.dead_letters[0]["reason_code"],  # pylint: disable=protected-access
            "processing_exception",
        )

    async def test_dedupe_and_dead_letter_error_paths(self) -> None:
        logger = Mock()
        dead_letter_rel = _DeadLetterFailingRelational()
        ext_dead_letter_fail = _new_extension(
            config=_make_config(),
            relational_storage_gateway=dead_letter_rel,
            logging_gateway=logger,
        )
        await ext_dead_letter_fail._record_dead_letter(  # pylint: disable=protected-access
            event_type="malformed",
            event_payload={"a": 1},
            reason_code="bad",
        )
        self.assertTrue(
            any("Failed to write Signal dead-letter event." in str(call.args[0]) for call in logger.error.call_args_list)
        )

        dedupe_err_ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=_DedupeErrorRelational(),
            logging_gateway=logger,
        )
        duplicate = await dedupe_err_ext._is_duplicate_event(  # pylint: disable=protected-access
            "message",
            {"a": 1},
        )
        self.assertFalse(duplicate)

        rel = _DedupeUpdateErrorRelational()
        rel.event_dedup[("message", dedupe_err_ext._build_event_dedupe_key("message", {"a": 2}))] = {}  # pylint: disable=protected-access
        update_err_ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=rel,
            logging_gateway=logger,
        )
        duplicate = await update_err_ext._is_duplicate_event(  # pylint: disable=protected-access
            "message",
            {"a": 2},
        )
        self.assertTrue(duplicate)
