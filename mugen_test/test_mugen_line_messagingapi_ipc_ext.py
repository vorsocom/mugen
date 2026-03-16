"""Unit tests for mugen.core.plugin.line.messagingapi.ipc_ext."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.service.ingress_routing import (
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.contract.service.ipc import IPCCommandRequest
from mugen.core.plugin.line.messagingapi import ipc_ext
from mugen.core.plugin.line.messagingapi.ipc_ext import LineMessagingAPIIPCExtension

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000201")


def _make_config(*, typing_enabled: bool = True, dedupe_ttl: int = 86400) -> SimpleNamespace:
    return SimpleNamespace(
        line=SimpleNamespace(
            webhook=SimpleNamespace(dedupe_ttl_seconds=dedupe_ttl),
            typing=SimpleNamespace(enabled=typing_enabled),
        )
    )


def _make_request(
    data: dict,
    command: str = "line_messagingapi_event",
    path_token: str = "line-path-token",
) -> IPCCommandRequest:
    payload = data
    if command == "line_messagingapi_event":
        payload = {
            "path_token": path_token,
            "payload": data,
        }
    return IPCCommandRequest(
        platform="line",
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
        reply_messages=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        push_messages=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        multicast_messages=AsyncMock(return_value={"ok": True, "status": 200, "data": {}}),
        emit_processing_signal=AsyncMock(return_value=True),
        download_media=AsyncMock(
            return_value={
                "path": "/tmp/file.bin",
                "mime_type": "application/octet-stream",
            }
        ),
        get_profile=AsyncMock(return_value={"ok": True, "data": {"displayName": "Line User"}}),
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
        if table == "line_messagingapi_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "line_messagingapi_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict) -> dict | None:
        if table != "line_messagingapi_event_dedup":
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
            identifier_value = "line-path-token"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="line",
                channel_key="line",
                client_profile_id=_CLIENT_PROFILE_ID,
                client_profile_key="line-a",
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
) -> LineMessagingAPIIPCExtension:
    return LineMessagingAPIIPCExtension(
        config=config,
        logging_gateway=logging_gateway or Mock(),
        relational_storage_gateway=(
            relational_storage_gateway or _MemoryRelational()
        ),
        messaging_service=messaging_service or _make_messaging_service(),
        user_service=user_service or _make_user_service(),
        line_client=client or _make_client(),
        ingress_routing_service=ingress_routing_service or _IngressRoutingStub(),
    )


def _message_event(*, text: str = "hello") -> dict:
    return {
        "type": "message",
        "webhookEventId": "evt-1",
        "replyToken": "reply-token-1",
        "source": {"type": "user", "userId": "U-1"},
        "message": {
            "id": "m-1",
            "type": "text",
            "text": text,
        },
    }


def _postback_event(*, data: str = "btn-1") -> dict:
    return {
        "type": "postback",
        "webhookEventId": "evt-2",
        "replyToken": "reply-token-2",
        "source": {"type": "user", "userId": "U-1"},
        "postback": {"data": data},
    }


def _media_event(*, message_type: str) -> dict:
    return {
        "type": "message",
        "webhookEventId": f"evt-{message_type}",
        "replyToken": "reply-token-3",
        "source": {"type": "user", "userId": "U-1"},
        "message": {
            "id": f"m-{message_type}",
            "type": message_type,
        },
    }


class TestMugenLineMessagingapiIpcExt(unittest.IsolatedAsyncioTestCase):
    """Covers event routing, outbound mapping, and reliability behavior."""

    async def test_provider_helpers_return_from_di_container(self) -> None:
        container = SimpleNamespace(
            line_client="client",
            config="config",
            logging_gateway="logger",
            relational_storage_gateway="rsg",
            messaging_service="ms",
            user_service="us",
        )
        with patch.object(ipc_ext.di, "container", new=container):
            self.assertEqual(ipc_ext._line_client_provider(), "client")
            self.assertEqual(ipc_ext._config_provider(), "config")
            self.assertEqual(ipc_ext._logging_gateway_provider(), "logger")
            self.assertEqual(ipc_ext._relational_storage_gateway_provider(), "rsg")
            self.assertEqual(ipc_ext._messaging_service_provider(), "ms")
            self.assertEqual(ipc_ext._user_service_provider(), "us")

    async def test_properties_and_process_command_dispatch(self) -> None:
        ext = _new_extension(config=_make_config())

        self.assertEqual(ext.platforms, ["line"])
        self.assertEqual(
            ext.ipc_commands,
            ["line_ingress_event", "line_messagingapi_event"],
        )

        with (
            patch.object(ext, "_line_ingress_event", new=AsyncMock()) as ingress_handler,
            patch.object(ext, "_line_messagingapi_event", new=AsyncMock()) as event_handler,
        ):
            handled_ingress = await ext.process_ipc_command(
                _make_request({"events": []}, command="line_ingress_event")
            )
            handled = await ext.process_ipc_command(
                _make_request({"events": []}, command="line_messagingapi_event")
            )
            unknown = await ext.process_ipc_command(
                _make_request({}, command="unknown")
            )

        ingress_handler.assert_awaited_once()
        event_handler.assert_awaited_once()
        self.assertTrue(handled_ingress.ok)
        self.assertEqual(handled_ingress.response, {"response": "OK"})
        self.assertTrue(handled.ok)
        self.assertEqual(handled.response, {"response": "OK"})
        self.assertFalse(unknown.ok)
        self.assertEqual(unknown.code, "not_found")

    async def test_line_ingress_event_validates_payload_and_processes_event(self) -> None:
        ext = _new_extension(config=_make_config())

        with self.assertRaisesRegex(TypeError, "payload.event must be a dict"):
            await ext._line_ingress_event(  # pylint: disable=protected-access
                _make_request({"payload": []}, command="line_ingress_event")
            )

        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value={"client_profile_id": _CLIENT_PROFILE_ID, "tenant_id": "tenant-a"}
        )
        ext._process_single_event = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        await ext._line_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "client_profile_id": str(_CLIENT_PROFILE_ID),
                    "payload": _message_event(),
                    "provider_context": {
                        "path_token": "line-path-token",
                        "ingress_route": {},
                    },
                },
                command="line_ingress_event",
            )
        )

        ext._process_single_event.assert_awaited_once()
        kwargs = ext._process_single_event.await_args.kwargs  # type: ignore[union-attr]
        self.assertTrue(kwargs["skip_dedupe"])
        self.assertEqual(kwargs["ingress_route"]["client_profile_id"], _CLIENT_PROFILE_ID)

        ext._process_single_event.reset_mock()
        ext._resolve_ingress_route = AsyncMock(  # type: ignore[method-assign]  # pylint: disable=protected-access
            return_value=None
        )
        await ext._line_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "payload": _message_event(),
                    "provider_context": {
                        "path_token": "line-path-token",
                        "ingress_route": {},
                    },
                },
                command="line_ingress_event",
            )
        )
        ext._resolve_ingress_route.assert_awaited_once()  # type: ignore[union-attr]

        ext._process_single_event.reset_mock()
        ext._resolve_ingress_route.reset_mock()  # type: ignore[union-attr]
        await ext._line_ingress_event(  # pylint: disable=protected-access
            _make_request(
                {
                    "payload": _message_event(),
                    "provider_context": {
                        "path_token": "line-path-token",
                        "ingress_route": {"client_profile_id": str(_CLIENT_PROFILE_ID)},
                    },
                },
                command="line_ingress_event",
            )
        )
        ext._resolve_ingress_route.assert_not_awaited()  # type: ignore[union-attr]

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

        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [_message_event()]})
        )

        messaging_service.handle_text_message.assert_awaited_once()
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "U-1")
        self.assertEqual(kwargs["sender"], "U-1")
        self.assertEqual(kwargs["message"], "hello")
        message_context = kwargs.get("message_context")
        self.assertIsInstance(message_context, list)
        self.assertEqual(message_context[-1]["type"], "ingress_route")
        user_service.add_known_user.assert_awaited_once_with("U-1", "Line User", "U-1")
        client.reply_messages.assert_awaited_once()
        client.emit_processing_signal.assert_any_await(
            "U-1",
            state="start",
            message_id="m-1",
        )
        client.emit_processing_signal.assert_any_await(
            "U-1",
            state="stop",
            message_id="m-1",
        )

    async def test_postback_routes_to_text_with_context(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(return_value=[])
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"U-1": "Line User"}),
        )

        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [_postback_event(data="btn-data")]})
        )

        messaging_service.handle_text_message.assert_awaited_once()
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "U-1")
        self.assertEqual(kwargs["sender"], "U-1")
        self.assertEqual(kwargs["message"], "btn-data")
        message_context = kwargs.get("message_context")
        self.assertIsInstance(message_context, list)
        self.assertEqual(message_context[0]["type"], "line_postback")
        self.assertEqual(message_context[-1]["type"], "ingress_route")

    async def test_lifecycle_events_route_to_message_handlers_only(self) -> None:
        handler = SimpleNamespace(
            message_types=["follow", "unfollow", "accountLink", "beacon"],
            platform_supported=lambda platform: platform == "line",
            handle_message=AsyncMock(return_value=[]),
        )
        messaging_service = _make_messaging_service()
        messaging_service.mh_extensions = [handler]
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"U-1": "Line User"}),
        )

        lifecycle_event = {
            "type": "follow",
            "webhookEventId": "evt-follow",
            "source": {"type": "user", "userId": "U-1"},
        }
        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [lifecycle_event]})
        )

        messaging_service.handle_text_message.assert_not_awaited()
        handler.handle_message.assert_awaited_once()

    async def test_non_user_event_is_ignored(self) -> None:
        logger = Mock()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            logging_gateway=logger,
        )

        event = {
            "type": "message",
            "source": {"type": "group", "groupId": "G-1"},
            "message": {"id": "m-1", "type": "text", "text": "hello"},
        }
        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [event]})
        )

        messaging_service.handle_text_message.assert_not_awaited()
        logger.info.assert_called_once()

    async def test_duplicate_event_is_ignored(self) -> None:
        logger = Mock()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"U-1": "Line User"}),
        )
        event = _message_event(text="hello")

        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [event]})
        )
        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [event]})
        )

        messaging_service.handle_text_message.assert_awaited_once()
        logger.debug.assert_any_call("Skip duplicate LINE event type=message.")

    async def test_media_messages_route_to_matching_handlers(self) -> None:
        cases = [
            ("audio", "handle_audio_message"),
            ("file", "handle_file_message"),
            ("image", "handle_image_message"),
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
                    user_service=_make_user_service(known_users={"U-1": "Line User"}),
                )

                await ext._line_messagingapi_event(  # pylint: disable=protected-access
                    _make_request({"events": [_media_event(message_type=message_type)]})
                )

                client.download_media.assert_awaited()
                getattr(messaging_service, handler_name).assert_awaited_once()

    async def test_dispatch_response_supports_generic_and_line_envelopes(self) -> None:
        client = _make_client()
        ext = _new_extension(config=_make_config(), client=client)

        await ext._dispatch_message_responses(  # pylint: disable=protected-access
            responses=[
                {"type": "text", "content": "hello"},
                {"type": "image", "file": {"url": "https://example.com/a.png"}},
                {"type": "audio", "file": {"url": "https://example.com/a.m4a"}},
                {"type": "video", "file": {"url": "https://example.com/a.mp4"}},
                {"type": "file", "file": {"url": "https://example.com/a.txt", "name": "a.txt"}},
                {
                    "type": "line",
                    "op": "push",
                    "payload": {
                        "to": "U-2",
                        "messages": [{"type": "text", "text": "native"}],
                    },
                },
                {
                    "type": "line",
                    "op": "multicast",
                    "payload": {
                        "to": ["U-2", "U-3"],
                        "messages": [{"type": "text", "text": "native"}],
                    },
                },
            ],
            sender="U-1",
            reply_token="reply-token-1",
        )

        client.reply_messages.assert_awaited_once()
        self.assertGreaterEqual(client.push_messages.await_count, 1)
        client.multicast_messages.assert_awaited_once()

    async def test_dispatch_response_reply_fallback_and_invalid_shapes(self) -> None:
        logger = Mock()
        client = _make_client()
        client.reply_messages = AsyncMock(return_value={"ok": False, "status": 500})
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )

        await ext._dispatch_message_responses(  # pylint: disable=protected-access
            responses=[
                {
                    "type": "line",
                    "op": "reply",
                    "payload": {
                        "messages": [{"type": "text", "text": "native"}],
                    },
                },
                {"type": "text", "content": "hello"},
                {"type": "audio", "file": {"url": "http://example.com/a.m4a"}},
                {"type": "unknown"},
            ],
            sender="U-1",
            reply_token="reply-token-1",
        )

        client.push_messages.assert_awaited()
        logger.warning.assert_any_call(
            "Reject LINE audio response with non-HTTPS media URL."
        )
        logger.error.assert_any_call("Unsupported response type: unknown.")

    async def test_internal_error_paths_and_dead_letter_recording(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
            logging_gateway=logger,
        )

        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [123]})
        )
        self.assertEqual(len(relational.dead_letters), 1)
        self.assertEqual(relational.dead_letters[0]["reason_code"], "malformed_payload")

        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request("bad-data")  # type: ignore[arg-type]
        )
        self.assertEqual(len(relational.dead_letters), 2)
        self.assertEqual(relational.dead_letters[1]["reason_code"], "malformed_payload")

    async def test_dead_letter_and_dedupe_failures_do_not_raise(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            messaging_service=messaging_service,
            logging_gateway=logger,
        )

        class _BrokenRelational:
            async def insert_one(self, *_args, **_kwargs):
                raise SQLAlchemyError("db down")

            async def update_one(self, *_args, **_kwargs):
                raise SQLAlchemyError("db down")

        ext._relational_storage_gateway = _BrokenRelational()  # pylint: disable=protected-access
        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": [_message_event()]})
        )
        logger.error.assert_any_call(
            "LINE dedupe lookup failed. error=SQLAlchemyError: db down"
        )

    async def test_resolve_and_api_call_helper_edges(self) -> None:
        ext_bad = _new_extension(config=_make_config(dedupe_ttl="bad"))  # type: ignore[arg-type]
        self.assertEqual(
            ext_bad._resolve_event_dedup_ttl_seconds(),  # pylint: disable=protected-access
            ext_bad._default_event_dedup_ttl_seconds,  # pylint: disable=protected-access
        )

        ext_zero = _new_extension(config=_make_config(dedupe_ttl=0))
        self.assertEqual(
            ext_zero._resolve_event_dedup_ttl_seconds(),  # pylint: disable=protected-access
            ext_zero._default_event_dedup_ttl_seconds,  # pylint: disable=protected-access
        )

        self.assertFalse(
            ext_zero._api_call_succeeded(None)  # pylint: disable=protected-access
        )
        self.assertTrue(
            ext_zero._api_call_succeeded({"ok": True, "status": None})  # pylint: disable=protected-access
        )
        self.assertFalse(
            ext_zero._api_call_succeeded({"ok": True, "status": "200"})  # pylint: disable=protected-access
        )

    async def test_ingress_router_default_provider_is_lazy_and_cached(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = LineMessagingAPIIPCExtension(
            config=_make_config(),
            logging_gateway=logger,
            relational_storage_gateway=relational,
            messaging_service=_make_messaging_service(),
            user_service=_make_user_service(),
            line_client=_make_client(),
            ingress_routing_service=None,
        )
        sentinel_router = object()
        with patch.object(
            ipc_ext,
            "DefaultIngressRoutingService",
            return_value=sentinel_router,
        ) as default_router_cls:
            first = ext._ingress_router()  # pylint: disable=protected-access
            second = ext._ingress_router()  # pylint: disable=protected-access

        self.assertIs(first, sentinel_router)
        self.assertIs(second, sentinel_router)
        default_router_cls.assert_called_once_with(
            relational_storage_gateway=relational,
            logging_gateway=logger,
        )

    async def test_merge_ingress_metadata_normalizes_non_dict_metadata(self) -> None:
        merged = LineMessagingAPIIPCExtension._merge_ingress_metadata(
            payload={"metadata": "invalid", "event": "x"},  # pylint: disable=protected-access
            ingress_route={"tenant_slug": "tenant-a"},
        )
        self.assertEqual(
            merged["metadata"],
            {
                "ingress_route": {"tenant_slug": "tenant-a"},
            },
        )

    async def test_resolve_ingress_route_unresolved_records_reason_variants(self) -> None:
        logger = Mock()
        routing_service = SimpleNamespace(
            resolve=AsyncMock(
                side_effect=[
                    IngressRouteResolution(
                        ok=False,
                        reason_code="missing_binding",
                        reason_detail="binding not found",
                    ),
                    IngressRouteResolution(
                        ok=False,
                        reason_code="route_unresolved",
                        reason_detail=None,
                    ),
                ]
            )
        )
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
            ingress_routing_service=routing_service,
        )
        with patch.object(
            ext,
            "_record_dead_letter",
            new=AsyncMock(),
        ) as record_dead_letter:
            first = await ext._resolve_ingress_route(  # pylint: disable=protected-access
                path_token="tok-1",
                webhook_payload={"events": []},
            )
            second = await ext._resolve_ingress_route(  # pylint: disable=protected-access
                path_token="tok-2",
                webhook_payload={"events": []},
            )

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(
            ext._metrics.get("line.ipc.route.unresolved"),  # pylint: disable=protected-access
            2,
        )
        self.assertEqual(record_dead_letter.await_count, 2)
        self.assertEqual(
            record_dead_letter.await_args_list[0].kwargs["error_message"],
            "missing_binding: binding not found",
        )
        self.assertEqual(
            record_dead_letter.await_args_list[1].kwargs["error_message"],
            "route_unresolved",
        )
        logger.warning.assert_any_call(
            "Dropped LINE webhook due to unresolved ingress route "
            "reason_code=missing_binding path_token='tok-1'."
        )
        logger.warning.assert_any_call(
            "Dropped LINE webhook due to unresolved ingress route "
            "reason_code=route_unresolved path_token='tok-2'."
        )

    async def test_dead_letter_and_dedupe_branch_edges(self) -> None:
        logger = Mock()

        class _DeadLetterInsertFails:
            async def insert_one(self, *_args, **_kwargs):
                raise SQLAlchemyError("dead-letter down")

            async def update_one(self, *_args, **_kwargs):
                return None

        ext_dead_letter = _new_extension(
            config=_make_config(),
            relational_storage_gateway=_DeadLetterInsertFails(),
            logging_gateway=logger,
        )
        await ext_dead_letter._record_dead_letter(  # pylint: disable=protected-access
            event_type="event",
            event_payload={"x": 1},
            reason_code="reason",
            error_message="error",
        )
        logger.error.assert_any_call(
            "Failed to write LINE dead-letter event."
            " reason_code=reason"
            " error=SQLAlchemyError: dead-letter down"
        )

        class _DuplicateWithBrokenUpdate:
            async def insert_one(self, *_args, **_kwargs):
                raise IntegrityError("insert", {}, Exception("dup"))

            async def update_one(self, *_args, **_kwargs):
                raise SQLAlchemyError("update failed")

        ext_duplicate = _new_extension(
            config=_make_config(),
            relational_storage_gateway=_DuplicateWithBrokenUpdate(),
        )
        self.assertTrue(
            await ext_duplicate._is_duplicate_event(  # pylint: disable=protected-access
                "message",
                {"message": {"id": "m-1"}},
            )
        )

    async def test_reply_or_push_and_batch_failure_paths(self) -> None:
        logger = Mock()
        client = _make_client()
        client.push_messages = AsyncMock(return_value={"ok": False, "status": 500})
        client.reply_messages = AsyncMock(return_value={"ok": False, "status": 500})
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )
        ext._max_messages_per_request = 1  # pylint: disable=protected-access

        await ext._push_message_batches(  # pylint: disable=protected-access
            recipient="U-1",
            messages=[{"type": "text", "text": "a"}],
        )
        logger.warning.assert_any_call(
            "LINE push batch delivery failed "
            "recipient=U-1 response={'ok': False, 'status': 500}."
        )

        with patch.object(
            ext,
            "_split_message_batches",
            return_value=[],
        ):
            self.assertFalse(
                await ext._reply_or_push_messages(  # pylint: disable=protected-access
                    recipient="U-1",
                    reply_token="rt",
                    messages=[{"type": "text", "text": "a"}],
                )
            )

        used_reply_token = await ext._reply_or_push_messages(  # pylint: disable=protected-access
            recipient="U-1",
            reply_token="rt",
            messages=[{"type": "text", "text": "a"}],
        )
        self.assertTrue(used_reply_token)
        logger.warning.assert_any_call(
            "LINE reply delivery failed, falling back to push "
            "recipient=U-1 response={'ok': False, 'status': 500}."
        )

        await ext._reply_or_push_messages(  # pylint: disable=protected-access
            recipient="U-1",
            reply_token=None,
            messages=[{"type": "text", "text": "a"}],
        )
        logger.warning.assert_any_call(
            "LINE push delivery failed "
            "recipient=U-1 response={'ok': False, 'status': 500}."
        )

    async def test_line_message_normalization_edge_paths(self) -> None:
        logger = Mock()
        ext = _new_extension(config=_make_config(), logging_gateway=logger)

        self.assertIsNone(
            ext._line_message_from_response(  # pylint: disable=protected-access
                {"type": "text", "content": 123}
            )
        )
        self.assertIsNone(
            ext._line_message_from_response({"type": "audio"})  # pylint: disable=protected-access
        )

        audio = ext._line_message_from_response(  # pylint: disable=protected-access
            {
                "type": "audio",
                "file": {
                    "url": "https://example.com/a.m4a",
                    "duration": 2000,
                },
            }
        )
        self.assertEqual(audio["duration"], 2000)

        self.assertIsNone(
            ext._line_message_from_response(  # pylint: disable=protected-access
                {"type": "image", "file": {"url": "http://example.com/a.png"}}
            )
        )
        self.assertIsNone(
            ext._line_message_from_response(  # pylint: disable=protected-access
                {"type": "video", "file": {"url": "http://example.com/a.mp4"}}
            )
        )

        file_as_text = ext._line_message_from_response(  # pylint: disable=protected-access
            {"type": "file", "file": {"url": "https://example.com/a.txt"}}
        )
        self.assertEqual(file_as_text, {"type": "text", "text": "https://example.com/a.txt"})
        self.assertIsNone(
            ext._line_message_from_response(  # pylint: disable=protected-access
                {"type": "file", "file": {"url": "http://example.com/a.txt"}}
            )
        )

    async def test_handle_line_envelope_edge_paths(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )

        with patch.object(
            ext,
            "_push_message_batches",
            new=AsyncMock(),
        ) as push_batches:
            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={"type": "line", "op": "reply", "payload": {"messages": "bad"}},
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )

            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={
                        "type": "line",
                        "op": "reply",
                        "payload": {"messages": [{"type": "text", "text": "x"}]},
                    },
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )
            push_batches.assert_awaited()

            client.reply_messages = AsyncMock(return_value={"ok": True, "status": 200})
            self.assertTrue(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={
                        "type": "line",
                        "op": "reply",
                        "payload": {
                            "reply_token": "rt",
                            "messages": [{"type": "text", "text": "x"}],
                        },
                    },
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )

            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={"type": "line", "op": "push", "payload": {"messages": "bad"}},
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )

            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={
                        "type": "line",
                        "op": "push",
                        "payload": "invalid",
                        "messages": [{"type": "text", "text": "x"}],
                    },
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )
            push_batches.assert_any_await(
                recipient="U-1",
                messages=[{"type": "text", "text": "x"}],
            )

            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={"type": "line", "op": "multicast", "payload": {"to": "bad", "messages": []}},
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )
            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={"type": "line", "op": "multicast", "payload": {"to": ["U-1"], "messages": "bad"}},
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )

            client.multicast_messages = AsyncMock(return_value={"ok": False, "status": 500})
            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={
                        "type": "line",
                        "op": "multicast",
                        "payload": {"to": ["U-1"], "messages": [{"type": "text", "text": "x"}]},
                    },
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )

            self.assertFalse(
                await ext._handle_line_envelope_response(  # pylint: disable=protected-access
                    response={"type": "line", "op": "unknown", "payload": {}},
                    sender="U-1",
                    fallback_reply_token=None,
                )
            )

    async def test_dispatch_and_processing_signal_edge_paths(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )

        with patch.object(
            ext,
            "_reply_or_push_messages",
            new=AsyncMock(),
        ) as reply_or_push:
            await ext._dispatch_message_responses(  # pylint: disable=protected-access
                responses=[123],
                sender="U-1",
                reply_token="rt",
            )
            reply_or_push.assert_awaited_once_with(
                recipient="U-1",
                reply_token="rt",
                messages=[],
            )

        ext_typing_disabled = _new_extension(config=_make_config(typing_enabled=False), client=client)
        await ext_typing_disabled._emit_processing_signal(  # pylint: disable=protected-access
            sender="U-1",
            message_id="m-1",
            state="start",
        )

        ext_no_emitter = _new_extension(
            config=_make_config(),
            client=SimpleNamespace(),
            logging_gateway=logger,
        )
        await ext_no_emitter._emit_processing_signal(  # pylint: disable=protected-access
            sender="U-1",
            message_id="m-1",
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
            sender="U-1",
            message_id="m-1",
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
            sender="U-1",
            message_id="m-1",
            state="start",
        )

    async def test_register_sender_profile_edge_paths(self) -> None:
        logger = Mock()

        client_raises = _make_client()
        client_raises.get_profile = AsyncMock(side_effect=RuntimeError("boom"))
        user_service_raises = _make_user_service(known_users={})
        ext_raises = _new_extension(
            config=_make_config(),
            client=client_raises,
            user_service=user_service_raises,
            logging_gateway=logger,
        )
        await ext_raises._register_sender_if_unknown(sender="U-1")  # pylint: disable=protected-access
        user_service_raises.add_known_user.assert_awaited_once_with("U-1", "U-1", "U-1")

        client_non_dict_profile = _make_client()
        client_non_dict_profile.get_profile = AsyncMock(return_value={"data": "bad"})
        user_service_non_dict = _make_user_service(known_users={})
        ext_non_dict = _new_extension(
            config=_make_config(),
            client=client_non_dict_profile,
            user_service=user_service_non_dict,
        )
        await ext_non_dict._register_sender_if_unknown(sender="U-2")  # pylint: disable=protected-access
        user_service_non_dict.add_known_user.assert_awaited_once_with("U-2", "U-2", "U-2")

        client_blank_profile = _make_client()
        client_blank_profile.get_profile = AsyncMock(
            return_value={"data": {"displayName": "  "}}
        )
        user_service_blank = _make_user_service(known_users={})
        ext_blank = _new_extension(
            config=_make_config(),
            client=client_blank_profile,
            user_service=user_service_blank,
        )
        await ext_blank._register_sender_if_unknown(sender="U-3")  # pylint: disable=protected-access
        user_service_blank.add_known_user.assert_awaited_once_with("U-3", "U-3", "U-3")

    async def test_download_message_media_edge_paths(self) -> None:
        logger = Mock()
        client = _make_client()
        ext = _new_extension(
            config=_make_config(),
            client=client,
            logging_gateway=logger,
        )

        self.assertIsNone(
            await ext._download_message_media(message={})  # pylint: disable=protected-access
        )
        logger.error.assert_any_call("Malformed LINE media payload: missing id.")

        client.download_media = AsyncMock(return_value=None)
        self.assertIsNone(
            await ext._download_message_media(message={"id": "m-1"})  # pylint: disable=protected-access
        )

        client.download_media = AsyncMock(return_value={"path": "", "mime_type": "audio/ogg"})
        self.assertIsNone(
            await ext._download_message_media(message={"id": "m-2"})  # pylint: disable=protected-access
        )

    async def test_call_message_handlers_no_hits_logs_debug(self) -> None:
        logger = Mock()
        handler = SimpleNamespace(
            message_types=["text"],
            platform_supported=lambda _platform: False,
            handle_message=AsyncMock(),
        )
        messaging_service = _make_messaging_service()
        messaging_service.mh_extensions = [handler]
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            logging_gateway=logger,
        )

        await ext._call_message_handlers(  # pylint: disable=protected-access
            message={"x": 1},
            message_type="follow",
            sender="U-1",
        )
        logger.debug.assert_called_once_with("Unsupported LINE event type: follow.")

    async def test_call_message_handlers_skips_non_dict_ingress_route_context_items(
        self,
    ) -> None:
        handler = SimpleNamespace(
            message_types=["text"],
            platform_supported=lambda _platform: True,
            handle_message=AsyncMock(),
        )
        messaging_service = _make_messaging_service()
        messaging_service.mh_extensions = [handler]
        ext = _new_extension(
            config=_make_config(),
            messaging_service=messaging_service,
            logging_gateway=Mock(),
        )

        await ext._call_message_handlers(  # pylint: disable=protected-access
            message={"x": 1},
            message_type="text",
            sender="U-1",
            message_context=[
                {"type": "ingress_route", "content": "bad"},
                {"type": "ingress_route", "content": {"tenant_id": "tenant-1"}},
            ],
        )

        handler.handle_message.assert_awaited_once()
        self.assertEqual(
            handler.handle_message.await_args.kwargs["ingress_metadata"]["ingress_route"][
                "tenant_id"
            ],
            "tenant-1",
        )

    async def test_handle_message_event_edge_paths(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
        )

        await ext._handle_message_event(  # pylint: disable=protected-access
            event={"message": None},
            sender="U-1",
        )
        await ext._handle_message_event(  # pylint: disable=protected-access
            event={"message": {"id": "m-1"}},
            sender="U-1",
        )
        await ext._handle_message_event(  # pylint: disable=protected-access
            event={
                "message": {"id": "m-1", "type": "text", "text": 123},
                "replyToken": "rt",
            },
            sender="U-1",
        )
        logger.error.assert_any_call("Malformed LINE message payload.")
        logger.error.assert_any_call("Malformed LINE text message payload.")

        with (
            patch.object(ext, "_register_sender_if_unknown", new=AsyncMock()),
            patch.object(ext, "_emit_processing_signal", new=AsyncMock()),
            patch.object(ext, "_download_message_media", new=AsyncMock(return_value=None)),
            patch.object(ext, "_dispatch_message_responses", new=AsyncMock()) as dispatch,
        ):
            for message_type in ["audio", "file", "image", "video"]:
                await ext._handle_message_event(  # pylint: disable=protected-access
                    event={
                        "message": {"id": f"m-{message_type}", "type": message_type},
                        "replyToken": "rt",
                    },
                    sender="U-1",
                )
            self.assertEqual(dispatch.await_count, 4)

        with (
            patch.object(ext, "_register_sender_if_unknown", new=AsyncMock()),
            patch.object(ext, "_emit_processing_signal", new=AsyncMock()),
            patch.object(ext, "_call_message_handlers", new=AsyncMock()) as handlers,
        ):
            await ext._handle_message_event(  # pylint: disable=protected-access
                event={"message": {"id": "m-x", "type": "sticker"}},
                sender="U-1",
            )
            handlers.assert_awaited_once()

    async def test_handle_postback_edge_paths(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
        )

        await ext._handle_postback_event(  # pylint: disable=protected-access
            event={"postback": None},
            sender="U-1",
        )
        await ext._handle_postback_event(  # pylint: disable=protected-access
            event={"postback": {"data": None}},
            sender="U-1",
        )
        logger.error.assert_any_call("Malformed LINE postback payload.")
        logger.error.assert_any_call("LINE postback payload missing data field.")

        with (
            patch.object(ext, "_register_sender_if_unknown", new=AsyncMock()),
            patch.object(ext, "_emit_processing_signal", new=AsyncMock()),
            patch.object(ext, "_dispatch_message_responses", new=AsyncMock()) as dispatch,
        ):
            ext._messaging_service.handle_text_message = AsyncMock(return_value=[])  # pylint: disable=protected-access
            await ext._handle_postback_event(  # pylint: disable=protected-access
                event={"postback": {"params": {"k": "v"}}, "replyToken": "rt"},
                sender="U-1",
            )
            dispatch.assert_awaited_once()

    async def test_handle_lifecycle_unfollow_skips_registration(self) -> None:
        ext = _new_extension(config=_make_config())
        with (
            patch.object(ext, "_register_sender_if_unknown", new=AsyncMock()) as register,
            patch.object(ext, "_call_message_handlers", new=AsyncMock()) as handlers,
        ):
            await ext._handle_lifecycle_event(  # pylint: disable=protected-access
                event={"type": "unfollow"},
                sender="U-1",
                event_type="unfollow",
            )
            register.assert_not_awaited()
            handlers.assert_awaited_once()

    async def test_process_single_event_edge_paths(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
        )

        await ext._process_single_event({"source": None})  # pylint: disable=protected-access
        await ext._process_single_event({"source": {"type": "user"}})  # pylint: disable=protected-access
        await ext._process_single_event(  # pylint: disable=protected-access
            {"source": {"type": "user", "userId": "U-1"}}
        )
        logger.error.assert_any_call("Malformed LINE event source.")
        logger.error.assert_any_call("Malformed LINE event payload.")

        with (
            patch.object(ext, "_is_duplicate_event", new=AsyncMock(return_value=False)),
            patch.object(ext, "_call_message_handlers", new=AsyncMock()) as handlers,
        ):
            await ext._process_single_event(  # pylint: disable=protected-access
                {
                    "type": "custom-event",
                    "source": {"type": "user", "userId": "U-1"},
                }
            )
            handlers.assert_awaited_once()

    async def test_line_messagingapi_event_outer_failure_paths(self) -> None:
        logger = Mock()
        relational = _MemoryRelational()
        ext = _new_extension(
            config=_make_config(),
            relational_storage_gateway=relational,
            logging_gateway=logger,
        )

        await ext._line_messagingapi_event(  # pylint: disable=protected-access
            _make_request({"events": "bad"})
        )
        self.assertEqual(relational.dead_letters[-1]["reason_code"], "malformed_payload")

        with patch.object(
            ext,
            "_record_dead_letter",
            new=AsyncMock(side_effect=[RuntimeError("dead-letter boom"), None]),
        ):
            await ext._line_messagingapi_event(  # pylint: disable=protected-access
                _make_request({"events": [123]})
            )
        logger.error.assert_any_call(
            "Unhandled LINE webhook processing failure."
            " error=RuntimeError: dead-letter boom"
        )

    async def test_line_messagingapi_event_rejects_non_dict_outer_request(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
        )
        request = IPCCommandRequest(
            platform="line",
            command="line_messagingapi_event",
            data="bad-request-payload",
        )
        with patch.object(
            ext,
            "_record_dead_letter",
            new=AsyncMock(),
        ) as record_dead_letter:
            await ext._line_messagingapi_event(request)  # pylint: disable=protected-access

        record_dead_letter.assert_awaited_once_with(
            event_type="webhook",
            event_payload={},
            reason_code="malformed_payload",
            error_message="Malformed LINE webhook payload.",
        )
        logger.error.assert_any_call("Malformed LINE webhook payload.")

    async def test_line_messagingapi_event_returns_early_when_route_unresolved(self) -> None:
        ext = _new_extension(config=_make_config())
        with (
            patch.object(
                ext,
                "_resolve_ingress_route",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                ext,
                "_process_single_event",
                new=AsyncMock(),
            ) as process_single_event,
        ):
            await ext._line_messagingapi_event(  # pylint: disable=protected-access
                _make_request({"events": [_message_event()]})
            )

        process_single_event.assert_not_awaited()
        self.assertIsNone(
            ext._metrics.get("line.ipc.event.processed_ok")  # pylint: disable=protected-access
        )

    async def test_line_messagingapi_event_skips_routes_without_client_profile_id(
        self,
    ) -> None:
        ext = _new_extension(config=_make_config())
        with (
            patch.object(
                ext,
                "_resolve_ingress_route",
                new=AsyncMock(return_value={"tenant_id": "tenant-a"}),
            ),
            patch.object(
                ext,
                "_process_single_event",
                new=AsyncMock(),
            ) as process_single_event,
        ):
            await ext._line_messagingapi_event(  # pylint: disable=protected-access
                _make_request({"events": [_message_event()]})
            )

        process_single_event.assert_not_awaited()

    async def test_line_messagingapi_event_process_exception_records_dead_letter(self) -> None:
        logger = Mock()
        ext = _new_extension(
            config=_make_config(),
            logging_gateway=logger,
        )

        with (
            patch.object(
                ext,
                "_process_single_event",
                new=AsyncMock(side_effect=RuntimeError("event boom")),
            ),
            patch.object(
                ext,
                "_record_dead_letter",
                new=AsyncMock(),
            ) as record_dead_letter,
        ):
            await ext._line_messagingapi_event(  # pylint: disable=protected-access
                _make_request({"events": [{"type": "message"}]})
            )

        record_dead_letter.assert_awaited_once_with(
            event_type="message",
            event_payload={"type": "message"},
            reason_code="processing_exception",
            error_message="RuntimeError: event boom",
        )
        logger.error.assert_any_call(
            "Unhandled LINE event processing failure."
            " error=RuntimeError: event boom"
        )
