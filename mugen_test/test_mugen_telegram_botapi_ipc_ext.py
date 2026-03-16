"""Unit tests for mugen.core.plugin.telegram.botapi.ipc_ext."""

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
from mugen.core.plugin.telegram.botapi import ipc_ext
from mugen.core.plugin.telegram.botapi.ipc_ext import TelegramBotAPIIPCExtension

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000202")


def _make_config(*, typing_enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        telegram=SimpleNamespace(
            webhook=SimpleNamespace(dedupe_ttl_seconds=86400),
            typing=SimpleNamespace(enabled=typing_enabled),
        )
    )


def _make_request(
    data: dict,
    command: str = "telegram_botapi_update",
    path_token: str = "telegram-path-token",
) -> IPCCommandRequest:
    payload = data
    if command == "telegram_botapi_update":
        payload = {
            "path_token": path_token,
            "payload": data,
        }
    return IPCCommandRequest(
        platform="telegram",
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
        answer_callback_query=AsyncMock(return_value={"ok": True, "data": {}}),
        emit_processing_signal=AsyncMock(return_value=True),
        download_media=AsyncMock(
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
        if table == "telegram_botapi_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "telegram_botapi_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict) -> dict | None:
        if table != "telegram_botapi_event_dedup":
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
            identifier_value = "telegram-path-token"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="telegram",
                channel_key="telegram",
                client_profile_id=_CLIENT_PROFILE_ID,
                client_profile_key="telegram-a",
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
) -> TelegramBotAPIIPCExtension:
    return TelegramBotAPIIPCExtension(
        config=config,
        logging_gateway=logging_gateway or Mock(),
        relational_storage_gateway=(
            relational_storage_gateway or _MemoryRelational()
        ),
        messaging_service=messaging_service or _make_messaging_service(),
        user_service=user_service or _make_user_service(),
        telegram_client=client or _make_client(),
        ingress_routing_service=ingress_routing_service or _IngressRoutingStub(),
    )


def _make_private_text_message_update(*, text: str = "hello") -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "chat": {"id": 2001, "type": "private"},
            "from": {"id": 3001, "first_name": "Alice"},
            "text": text,
        },
    }


def _make_non_private_text_message_update() -> dict:
    return {
        "update_id": 2,
        "message": {
            "message_id": 11,
            "chat": {"id": -100, "type": "group"},
            "from": {"id": 3002, "first_name": "Bob"},
            "text": "hello",
        },
    }


def _make_callback_update(*, data: str = "btn-1") -> dict:
    return {
        "update_id": 3,
        "callback_query": {
            "id": "cq-1",
            "from": {"id": 3001, "first_name": "Alice"},
            "data": data,
            "message": {
                "message_id": 15,
                "chat": {"id": 2001, "type": "private"},
            },
        },
    }


def _make_media_message_update(*, message_type: str, file_id: str = "f-1") -> dict:
    payload = {
        "update_id": 4,
        "message": {
            "message_id": 20,
            "chat": {"id": 2001, "type": "private"},
            "from": {"id": 3001, "first_name": "Alice"},
        },
    }
    if message_type == "photo":
        payload["message"]["photo"] = [
            {"file_id": "small", "file_size": 5},
            {"file_id": file_id, "file_size": 10},
        ]
    else:
        payload["message"][message_type] = {"file_id": file_id}
    return payload


class TestMugenTelegramBotapiIpcExt(unittest.IsolatedAsyncioTestCase):
    """Covers update routing, media processing, and reliability behavior."""

    async def test_properties_and_process_command_dispatch(self) -> None:
        ext = _new_extension(config=_make_config())

        self.assertEqual(ext.platforms, ["telegram"])
        self.assertEqual(
            ext.ipc_commands,
            ["telegram_ingress_event", "telegram_botapi_update"],
        )

        with (
            patch.object(ext, "_telegram_ingress_event", new=AsyncMock()) as ingress_handler,
            patch.object(ext, "_telegram_botapi_update", new=AsyncMock()) as update_handler,
        ):
            handled_ingress = await ext.process_ipc_command(
                _make_request(
                    {},
                    command="telegram_ingress_event",
                )
            )
            handled = await ext.process_ipc_command(
                _make_request(
                    {},
                    command="telegram_botapi_update",
                )
            )
            unknown = await ext.process_ipc_command(
                _make_request(
                    {},
                    command="unknown",
                )
            )

        ingress_handler.assert_awaited_once()
        update_handler.assert_awaited_once()
        self.assertEqual(handled_ingress.response, {"response": "OK"})
        self.assertTrue(handled_ingress.ok)
        self.assertEqual(handled.response, {"response": "OK"})
        self.assertTrue(handled.ok)
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.code, "not_found")

    async def test_telegram_ingress_event_validates_and_dispatches_updates(self) -> None:
        ext = _new_extension(config=_make_config())

        with self.assertRaisesRegex(TypeError, "payload.event must be a dict"):
            await ext._telegram_ingress_event(  # pylint: disable=protected-access
                _make_request({"payload": []}, command="telegram_ingress_event")
            )

        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={"client_profile_id": _CLIENT_PROFILE_ID, "tenant_id": "tenant-a"}
        )
        ext._handle_message_update = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        ext._handle_callback_query_update = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        await ext._telegram_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "payload": {
                        "update": {"update_id": 1},
                        "message": {"chat": {"id": 1}, "from": {"id": 2}},
                        "callback_query": {
                            "id": "cb-1",
                            "from": {"id": 3},
                            "message": {"chat": {"id": 4}},
                        },
                    },
                    "provider_context": {"path_token": "telegram-path", "ingress_route": {}},
                },
                command="telegram_ingress_event",
            )
        )

        ext._handle_message_update.assert_awaited_once()
        ext._handle_callback_query_update.assert_awaited_once()

        ext._handle_message_update.reset_mock()
        ext._handle_callback_query_update.reset_mock()
        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=None
        )

        await ext._telegram_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "payload": {
                        "update_id": 2,
                        "callback_query": {
                            "message": {},
                        },
                    },
                    "provider_context": {"path_token": "telegram-path", "ingress_route": {}},
                },
                command="telegram_ingress_event",
            )
        )
        ext._handle_message_update.assert_not_awaited()
        ext._handle_callback_query_update.assert_not_awaited()

        ext._handle_callback_query_update.reset_mock()
        ext._resolve_ingress_route.reset_mock()  # type: ignore[union-attr]
        await ext._telegram_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "payload": {
                        "update_id": 3,
                        "message": {"chat": {"id": 1}},
                    },
                    "provider_context": {
                        "path_token": "telegram-path",
                        "ingress_route": {"client_profile_id": str(_CLIENT_PROFILE_ID)},
                    },
                },
                command="telegram_ingress_event",
            )
        )
        ext._resolve_ingress_route.assert_not_awaited()  # type: ignore[union-attr]

        ext._handle_message_update.reset_mock()
        ext._handle_callback_query_update.reset_mock()
        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={"client_profile_id": _CLIENT_PROFILE_ID, "tenant_id": "tenant-a"}
        )
        await ext._telegram_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "payload": {
                        "update": {"update_id": 4},
                        "callback_query": {
                            "id": "cb-only",
                            "message": {"chat": {"id": 4}},
                        },
                    },
                    "provider_context": {"path_token": "telegram-path", "ingress_route": {}},
                },
                command="telegram_ingress_event",
            )
        )
        ext._handle_message_update.assert_not_awaited()
        ext._handle_callback_query_update.assert_awaited_once()

    async def test_text_message_routes_to_text_handler_and_registers_user(self) -> None:
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

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_private_text_message_update())
        )

        messaging_service.handle_text_message.assert_awaited_once()
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "2001")
        self.assertEqual(kwargs["sender"], "3001")
        self.assertEqual(kwargs["message"], "hello")
        self.assertIsInstance(kwargs.get("message_context"), list)
        self.assertEqual(kwargs["message_context"][-1]["type"], "ingress_route")
        user_service.add_known_user.assert_awaited_once_with("3001", "Alice", "2001")
        client.send_text_message.assert_awaited_once()
        client.emit_processing_signal.assert_any_await(
            "2001",
            state="start",
        )
        client.emit_processing_signal.assert_any_await(
            "2001",
            state="stop",
        )

    async def test_telegram_botapi_update_returns_without_route_client_profile(self) -> None:
        ext = _new_extension(config=_make_config())
        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={"tenant_id": "tenant-a"}
        )
        ext._handle_message_update = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_private_text_message_update())
        )

        ext._handle_message_update.assert_not_awaited()

    async def test_slash_command_routes_as_text_with_context(self) -> None:
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
        )

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_private_text_message_update(text="/start now"))
        )

        context = messaging_service.handle_text_message.await_args.kwargs["message_context"]
        self.assertEqual(context[0]["type"], "telegram_command")

    async def test_non_private_message_is_ignored(self) -> None:
        logger = Mock()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            logging_gateway=logger,
        )

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_non_private_text_message_update())
        )

        messaging_service.handle_text_message.assert_not_awaited()
        logger.info.assert_called_once()

    async def test_callback_auto_ack_and_routes_to_text_with_context(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(return_value=[])
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
        )

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_callback_update(data="btn-data"))
        )

        client.answer_callback_query.assert_any_await(callback_query_id="cq-1")
        messaging_service.handle_text_message.assert_awaited_once()
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "2001")
        self.assertEqual(kwargs["sender"], "3001")
        self.assertEqual(kwargs["message"], "btn-data")
        context = kwargs.get("message_context")
        self.assertIsInstance(context, list)
        self.assertEqual(context[0]["type"], "telegram_callback")
        self.assertEqual(context[-1]["type"], "ingress_route")

    async def test_callback_missing_data_is_logged(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
        )

        update = _make_callback_update(data="btn")
        update["callback_query"].pop("data")
        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(update)
        )

        logger.error.assert_any_call("Telegram callback payload missing data field.")

    async def test_media_messages_route_to_matching_handlers(self) -> None:
        cases = [
            ("audio", "handle_audio_message"),
            ("document", "handle_file_message"),
            ("photo", "handle_image_message"),
            ("video", "handle_video_message"),
        ]

        for message_type, handler_name in cases:
            with self.subTest(message_type=message_type):
                client = _make_client()
                messaging_service = _make_messaging_service()
                ext = _new_extension(
                    config=_make_config(),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=_make_user_service(known_users={"3001": "Alice"}),
                )

                await ext._telegram_botapi_update(  # pylint: disable=protected-access
                    _make_request(_make_media_message_update(message_type=message_type))
                )

                client.download_media.assert_awaited()
                getattr(messaging_service, handler_name).assert_awaited_once()

    async def test_media_download_missing_skips_handler(self) -> None:
        client = _make_client()
        client.download_media = AsyncMock(return_value=None)
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
        )

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_media_message_update(message_type="audio"))
        )

        messaging_service.handle_audio_message.assert_not_awaited()

    async def test_send_response_supports_generic_and_telegram_envelopes(self) -> None:
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client)

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": "hello"},
            "2001",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "audio", "file": {"id": "a1"}},
            "2001",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "file", "file": {"id": "d1"}},
            "2001",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "image", "file": {"id": "p1"}},
            "2001",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "video", "file": {"id": "v1"}},
            "2001",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "telegram",
                "op": "send_message",
                "text": "hello telegram",
                "chat_id": "2002",
                "reply_markup": {"inline_keyboard": []},
                "reply_to_message_id": 100,
            },
            "2001",
        )
        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "telegram",
                "op": "answer_callback",
                "callback_query_id": "cq-1",
                "text": "ack",
                "show_alert": True,
            },
            "2001",
        )

        client.send_text_message.assert_awaited()
        client.send_audio_message.assert_awaited_once()
        client.send_file_message.assert_awaited_once()
        client.send_image_message.assert_awaited_once()
        client.send_video_message.assert_awaited_once()
        client.answer_callback_query.assert_awaited()

    async def test_send_response_validation_and_unknown_types(self) -> None:
        logger = Mock()
        ext = _new_extension(config=_make_config(), logging_gateway=logger)

        invalid_payloads = [
            {"type": "text"},
            {"type": "audio"},
            {"type": "file"},
            {"type": "image"},
            {"type": "video"},
            {"type": "telegram", "op": "send_message"},
            {"type": "telegram", "op": "answer_callback"},
            {"type": "telegram", "op": "unknown"},
            {"type": "unknown"},
        ]

        for payload in invalid_payloads:
            await ext._send_response_to_user(payload, "2001")  # pylint: disable=protected-access

        logger.error.assert_any_call("Missing text content in response payload.")
        logger.error.assert_any_call("Missing audio payload in response.")
        logger.error.assert_any_call("Missing file payload in response.")
        logger.error.assert_any_call("Missing image payload in response.")
        logger.error.assert_any_call("Missing video payload in response.")
        logger.error.assert_any_call("Missing Telegram send_message text payload.")
        logger.error.assert_any_call(
            "Missing callback_query_id for Telegram answer_callback op."
        )
        logger.error.assert_any_call("Unsupported Telegram response op: unknown.")
        logger.error.assert_any_call("Unsupported response type: unknown.")

    async def test_dedupe_and_dead_letter_paths(self) -> None:
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
        )
        update = _make_private_text_message_update()

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(update)
        )
        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(update)
        )

        self.assertEqual(len(relational.event_dedup), 1)

        malformed = IPCCommandRequest(
            platform="telegram",
            command="telegram_botapi_update",
            data=[],
        )
        await ext._telegram_botapi_update(malformed)  # pylint: disable=protected-access
        self.assertEqual(len(relational.dead_letters), 1)

    async def test_dead_letter_and_dedupe_sqlalchemy_errors_do_not_raise(self) -> None:
        relational = _MemoryRelational()

        async def _raise_sqlalchemy(*_args, **_kwargs):
            raise SQLAlchemyError("db down")

        relational.insert_one = AsyncMock(side_effect=_raise_sqlalchemy)
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
            logging_gateway=logger,
        )

        await ext._record_dead_letter(  # pylint: disable=protected-access
            event_type="webhook",
            event_payload={"update_id": 1},
            reason_code="err",
            error_message="boom",
        )
        duplicate = await ext._is_duplicate_event(  # pylint: disable=protected-access
            "message",
            {"id": "1"},
        )
        self.assertFalse(duplicate)

    async def test_typing_disabled_skips_processing_signals(self) -> None:
        client = _make_client()
        ext = _new_extension(
            config=_make_config(typing_enabled=False),
            client=client,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
        )

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_private_text_message_update())
        )

        client.emit_processing_signal.assert_not_awaited()

    async def test_update_exception_records_dead_letter(self) -> None:
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
        )

        with patch.object(
            ext,
            "_handle_message_update",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            await ext._telegram_botapi_update(  # pylint: disable=protected-access
                _make_request(_make_private_text_message_update())
            )

        self.assertEqual(len(relational.dead_letters), 1)

    async def test_provider_helpers_and_ttl_fallbacks(self) -> None:
        container = SimpleNamespace(
            telegram_client="client",
            config="cfg",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
            messaging_service="msg",
            user_service="usr",
        )
        with patch.object(ipc_ext.di, "container", new=container):
            self.assertEqual(ipc_ext._telegram_client_provider(), "client")
            self.assertEqual(ipc_ext._config_provider(), "cfg")
            self.assertEqual(ipc_ext._logging_gateway_provider(), "logger")
            self.assertEqual(ipc_ext._relational_storage_gateway_provider(), "rsg")
            self.assertEqual(ipc_ext._messaging_service_provider(), "msg")
            self.assertEqual(ipc_ext._user_service_provider(), "usr")

        invalid_config = _make_config()
        invalid_config.telegram.webhook.dedupe_ttl_seconds = "bad"
        invalid_ttl_ext = _new_extension(config=invalid_config)
        self.assertEqual(invalid_ttl_ext._event_dedup_ttl_seconds, 86400)  # pylint: disable=protected-access

        nonpositive_config = _make_config()
        nonpositive_config.telegram.webhook.dedupe_ttl_seconds = 0
        nonpositive_ttl_ext = _new_extension(config=nonpositive_config)
        self.assertEqual(nonpositive_ttl_ext._event_dedup_ttl_seconds, 86400)  # pylint: disable=protected-access

    async def test_duplicate_update_path_tolerates_update_error(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
            logging_gateway=logger,
        )
        payload = {"id": "event-1"}
        dedupe_key = ext._build_event_dedupe_key("message", payload)  # pylint: disable=protected-access
        relational.event_dedup[("message", dedupe_key)] = {
            "event_type": "message",
            "dedupe_key": dedupe_key,
        }
        relational.insert_one = AsyncMock(side_effect=IntegrityError("insert", {}, Exception("dup")))
        relational.update_one = AsyncMock(side_effect=SQLAlchemyError("update-failed"))

        self.assertTrue(await ext._is_duplicate_event("message", payload))  # pylint: disable=protected-access
        self.assertEqual(ext._coerce_user_id("3001"), "3001")  # pylint: disable=protected-access
        self.assertIsNone(ext._coerce_user_id(""))  # pylint: disable=protected-access

    async def test_emit_processing_signal_edge_branches(self) -> None:
        logger = Mock()
        no_emitter_ext = _new_extension(
            config=_make_config(),
            client=SimpleNamespace(),
            logging_gateway=logger,
        )
        await no_emitter_ext._emit_processing_signal(  # pylint: disable=protected-access
            chat_id="2001",
            message_id=None,
            state="start",
        )

        failing_emitter = SimpleNamespace(emit_processing_signal=AsyncMock(return_value=False))
        failing_ext = _new_extension(
            config=_make_config(),
            client=failing_emitter,
            logging_gateway=logger,
        )
        await failing_ext._emit_processing_signal(  # pylint: disable=protected-access
            chat_id="2001",
            message_id=None,
            state="start",
        )

        raising_emitter = SimpleNamespace(
            emit_processing_signal=AsyncMock(side_effect=RuntimeError("boom"))
        )
        raising_ext = _new_extension(
            config=_make_config(),
            client=raising_emitter,
            logging_gateway=logger,
        )
        await raising_ext._emit_processing_signal(  # pylint: disable=protected-access
            chat_id="2001",
            message_id=None,
            state="start",
        )

        logger.warning.assert_called()

    async def test_register_sender_and_download_media_edge_branches(self) -> None:
        user_service = _make_user_service(known_users={})
        client = _make_client()
        client.download_media = AsyncMock(return_value={"path": "", "mime_type": "audio/mp3"})
        ext = _new_extension(
            config=_make_config(),
            user_service=user_service,
            client=client,
            logging_gateway=Mock(),
        )
        await ext._register_sender_if_unknown(  # pylint: disable=protected-access
            sender="3001",
            room_id="2001",
            user_obj={"username": "alice-user"},
        )
        await ext._register_sender_if_unknown(  # pylint: disable=protected-access
            sender="3002",
            room_id="2001",
            user_obj=None,
        )
        await ext._register_sender_if_unknown(  # pylint: disable=protected-access
            sender="3003",
            room_id="2001",
            user_obj={"first_name": "", "username": ""},
        )
        self.assertEqual(user_service.add_known_user.await_count, 3)
        user_service.add_known_user.assert_any_await("3001", "alice-user", "2001")
        user_service.add_known_user.assert_any_await("3002", "3002", "2001")
        user_service.add_known_user.assert_any_await("3003", "3003", "2001")
        self.assertIsNone(
            await ext._download_message_media(file_id="file-1")  # pylint: disable=protected-access
        )

    async def test_send_response_optional_fields_and_reply_id_branch(self) -> None:
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client, logging_gateway=Mock())

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "telegram",
                "op": "send_message",
                "text": "hello",
                "reply_markup": [],
                "reply_to_message_id": "bad",
            },
            "2001",
        )
        send_args = client.send_text_message.await_args.kwargs
        self.assertIsNone(send_args["reply_markup"])
        self.assertIsNone(send_args["reply_to_message_id"])

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "telegram",
                "op": "answer_callback",
                "callback_query_id": "cq-1",
                "text": 99,
                "show_alert": "no",
            },
            "2001",
        )
        answer_args = client.answer_callback_query.await_args.kwargs
        self.assertIsNone(answer_args["text"])
        self.assertIsNone(answer_args["show_alert"])

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "text",
                "content": "hello",
                "reply_to_message_id": 10,
            },
            "2001",
        )
        self.assertEqual(client.send_text_message.await_args.kwargs["reply_to_message_id"], 10)

    async def test_message_media_branch_fallthrough_paths(self) -> None:
        logger = Mock()
        client = _make_client()
        client.download_media = AsyncMock(return_value=None)
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
            logging_gateway=logger,
        )

        audio_missing = _make_media_message_update(message_type="audio", file_id="")
        await ext._telegram_botapi_update(_make_request(audio_missing))  # pylint: disable=protected-access

        doc_missing = _make_media_message_update(message_type="document", file_id="")
        await ext._telegram_botapi_update(_make_request(doc_missing))  # pylint: disable=protected-access

        doc_download_none = _make_media_message_update(message_type="document", file_id="doc-1")
        await ext._telegram_botapi_update(_make_request(doc_download_none))  # pylint: disable=protected-access

        photo_no_candidates = _make_media_message_update(message_type="photo")
        photo_no_candidates["message"]["photo"] = [1, "bad"]
        await ext._telegram_botapi_update(_make_request(photo_no_candidates))  # pylint: disable=protected-access

        photo_missing_file_id = _make_media_message_update(message_type="photo")
        photo_missing_file_id["message"]["photo"] = [{"file_size": 10}]
        await ext._telegram_botapi_update(_make_request(photo_missing_file_id))  # pylint: disable=protected-access

        photo_download_none = _make_media_message_update(message_type="photo", file_id="photo-1")
        await ext._telegram_botapi_update(_make_request(photo_download_none))  # pylint: disable=protected-access

        video_missing = _make_media_message_update(message_type="video", file_id="")
        await ext._telegram_botapi_update(_make_request(video_missing))  # pylint: disable=protected-access

        video_download_none = _make_media_message_update(message_type="video", file_id="video-1")
        await ext._telegram_botapi_update(_make_request(video_download_none))  # pylint: disable=protected-access

        unsupported = {
            "update_id": 9,
            "message": {
                "chat": {"id": 2001, "type": "private"},
                "from": {"id": 3001, "first_name": "Alice"},
            },
        }
        await ext._telegram_botapi_update(_make_request(unsupported))  # pylint: disable=protected-access

        malformed = _make_private_text_message_update()
        malformed["message"]["chat"] = {"type": "private"}
        await ext._telegram_botapi_update(_make_request(malformed))  # pylint: disable=protected-access
        logger.error.assert_any_call("Malformed Telegram message payload.")

    async def test_callback_edge_paths_and_response_dispatch(self) -> None:
        logger = Mock()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[{"type": "text", "content": "callback-reply"}]
        )
        client = _make_client()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
            relational_storage_gateway=_MemoryRelational(),
        )

        missing_id = _make_callback_update(data="btn")
        missing_id["callback_query"]["id"] = None
        missing_id["callback_query"]["message"] = "bad"
        await ext._telegram_botapi_update(_make_request(missing_id))  # pylint: disable=protected-access

        duplicate_callback = _make_callback_update(data="dup")
        await ext._telegram_botapi_update(_make_request(duplicate_callback))  # pylint: disable=protected-access
        await ext._telegram_botapi_update(_make_request(duplicate_callback))  # pylint: disable=protected-access

        non_private_callback = _make_callback_update(data="x")
        non_private_callback["callback_query"]["message"]["chat"]["type"] = "group"
        await ext._telegram_botapi_update(_make_request(non_private_callback))  # pylint: disable=protected-access

        malformed_sender = _make_callback_update(data="x")
        malformed_sender["callback_query"]["from"] = {}
        await ext._telegram_botapi_update(_make_request(malformed_sender))  # pylint: disable=protected-access

        no_message_id_callback = _make_callback_update(data="route")
        no_message_id_callback["callback_query"]["message"].pop("message_id")
        await ext._telegram_botapi_update(_make_request(no_message_id_callback))  # pylint: disable=protected-access

        client.send_text_message.assert_awaited()
        logger.debug.assert_any_call("Skip duplicate Telegram callback event.")
        logger.error.assert_any_call("Malformed Telegram callback payload.")

    async def test_update_with_unsupported_payload_logs_debug(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            user_service=_make_user_service(known_users={"3001": "Alice"}),
        )
        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request({"update_id": 100})
        )
        logger.debug.assert_any_call("Unsupported Telegram update payload.")

    async def test_ingress_router_default_and_helper_fallback_branches(self) -> None:
        ext = TelegramBotAPIIPCExtension(
            config=_make_config(),
            logging_gateway=Mock(),
            relational_storage_gateway=_MemoryRelational(),
            messaging_service=_make_messaging_service(),
            user_service=_make_user_service(),
            telegram_client=_make_client(),
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

        self.assertIsNone(ext._coerce_nonempty_string(123))  # pylint: disable=protected-access
        self.assertEqual(  # pylint: disable=protected-access
            ext._normalize_ingress_route(None)["platform"],
            "telegram",
        )
        merged = ext._merge_ingress_metadata(  # pylint: disable=protected-access
            payload={"metadata": []},
            ingress_route={"tenant_slug": "tenant-a"},
        )
        self.assertEqual(merged["metadata"]["ingress_route"]["tenant_slug"], "tenant-a")

    async def test_missing_binding_route_is_dead_lettered_and_dropped(self) -> None:
        class _FallbackRouter:
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
            ingress_routing_service=_FallbackRouter(),
        )

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_private_text_message_update())
        )
        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            IPCCommandRequest(
                platform="telegram",
                command="telegram_botapi_update",
                data={
                    **_make_private_text_message_update(),
                    "path_token": "telegram-path-token",
                    "payload": "not-a-dict",
                },
            )
        )

        messaging.handle_text_message.assert_not_awaited()
        self.assertEqual(
            ext._metrics.get("telegram.ipc.route.unresolved"),  # pylint: disable=protected-access
            2,
        )
        self.assertEqual(len(relational.dead_letters), 2)
        self.assertEqual(relational.dead_letters[0]["reason_code"], "route_unresolved")
        self.assertEqual(relational.dead_letters[0]["error_message"], "missing_binding")
        self.assertEqual(relational.dead_letters[1]["reason_code"], "route_unresolved")
        self.assertEqual(relational.dead_letters[1]["error_message"], "missing_binding")
        logger.warning.assert_any_call(
            "Dropped Telegram webhook due to unresolved ingress route "
            "reason_code=missing_binding path_token='telegram-path-token'."
        )

        class _UnresolvedWithDetailRouter:
            async def resolve(self, request):  # noqa: ARG002
                return IngressRouteResolution(
                    ok=False,
                    reason_code=IngressRouteReason.RESOLUTION_ERROR.value,
                    reason_detail="detail",
                )

        ext_with_detail = _new_extension(
            config=_make_config(),
            logging_gateway=Mock(),
            relational_storage_gateway=_MemoryRelational(),
            ingress_routing_service=_UnresolvedWithDetailRouter(),
        )
        await ext_with_detail._resolve_ingress_route(  # pylint: disable=protected-access
            path_token="telegram-path-token",
            webhook_payload={"update_id": 1},
        )
        self.assertIn(
            "detail",
            str(ext_with_detail._relational_storage_gateway.dead_letters[0]["error_message"]),  # pylint: disable=protected-access
        )

    async def test_update_returns_early_when_ingress_route_resolution_returns_none(
        self,
    ) -> None:
        messaging = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging,
        )
        ext._resolve_ingress_route = AsyncMock(return_value=None)  # type: ignore[method-assign]  # pylint: disable=protected-access

        await ext._telegram_botapi_update(  # pylint: disable=protected-access
            _make_request(_make_private_text_message_update())
        )

        messaging.handle_text_message.assert_not_awaited()
