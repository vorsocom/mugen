"""Reliability E2E tests for Telegram webhook + IPC processing."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError

from mugen.core.contract.service.ingress_routing import (
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.plugin.telegram.botapi.api import webhook
from mugen.core.plugin.telegram.botapi.ipc_ext import TelegramBotAPIIPCExtension
from mugen.core.service.ipc import DefaultIPCService

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000206")


class _MemoryRelational:
    def __init__(self) -> None:
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict):
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

    async def update_one(self, table: str, where: dict, changes: dict):
        if table != "telegram_botapi_event_dedup":
            raise ValueError(f"Unsupported table: {table}")
        key = (where.get("event_type"), where.get("dedupe_key"))
        existing = self.event_dedup.get(key)
        if existing is None:
            return None
        existing.update(changes)
        return dict(existing)


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            platforms=["telegram"],
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=10.0,
                shutdown_timeout_seconds=60.0,
                phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            ),
        ),
        telegram=SimpleNamespace(
            bot=SimpleNamespace(token="BOT_TOKEN"),
            webhook=SimpleNamespace(
                path_token="path-token",
                secret_token="secret-token",
                dedupe_ttl_seconds=86400,
            ),
            typing=SimpleNamespace(enabled=True),
        ),
    )


def _make_client() -> SimpleNamespace:
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
                "size": 2,
            }
        ),
    )


class _IngressRoutingStub:
    async def resolve(self, request) -> IngressRouteResolution:
        identifier_value = request.identifier_value
        if not isinstance(identifier_value, str) or identifier_value.strip() == "":
            identifier_value = "path-token"
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
    logger: Mock,
    relational_gateway: _MemoryRelational,
    messaging_service: SimpleNamespace,
    user_service: SimpleNamespace,
    client: SimpleNamespace,
) -> TelegramBotAPIIPCExtension:
    return TelegramBotAPIIPCExtension(
        config=_make_config(),
        logging_gateway=logger,
        relational_storage_gateway=relational_gateway,
        messaging_service=messaging_service,
        user_service=user_service,
        telegram_client=client,
        ingress_routing_service=_IngressRoutingStub(),
    )


def _new_ipc_service(*, logger: Mock, ipc_ext: TelegramBotAPIIPCExtension) -> DefaultIPCService:
    ipc_service = DefaultIPCService(
        config=SimpleNamespace(),
        logging_gateway=logger,
    )
    ipc_service.bind_ipc_extension(ipc_ext)
    return ipc_service


def _make_text_update(*, text: str = "hello") -> dict:
    return {
        "update_id": 1001,
        "message": {
            "message_id": 2001,
            "chat": {"id": 3001, "type": "private"},
            "from": {"id": 4001, "first_name": "Known User"},
            "text": text,
        },
    }


def _make_callback_update(*, data: str = "btn-1") -> dict:
    return {
        "update_id": 1002,
        "callback_query": {
            "id": "cq-1",
            "from": {"id": 4001, "first_name": "Known User"},
            "data": data,
            "message": {
                "message_id": 2002,
                "chat": {"id": 3001, "type": "private"},
            },
        },
    }


def _make_audio_update(*, file_id: str = "audio-1") -> dict:
    return {
        "update_id": 1003,
        "message": {
            "message_id": 2003,
            "chat": {"id": 3001, "type": "private"},
            "from": {"id": 4001, "first_name": "Known User"},
            "audio": {"file_id": file_id},
        },
    }


class TestMugenTelegramReliabilityE2E(unittest.IsolatedAsyncioTestCase):
    """Exercises dedupe, callback, media, and dead-letter reliability behavior."""

    async def test_duplicate_update_delivery_is_processed_once(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"4001": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.telegram_botapi_webhook_event)
        payload = _make_text_update(text="hello")

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            first = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            second = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(first, {"response": "OK"})
        self.assertEqual(second, {"response": "OK"})
        messaging_service.handle_text_message.assert_awaited_once_with(
            "telegram",
            room_id="3001",
            sender="4001",
            message="hello",
            message_context=[
                {
                    "type": "ingress_route",
                    "content": {
                        "tenant_id": "11111111-1111-1111-1111-111111111111",
                        "tenant_slug": "tenant-a",
                        "platform": "telegram",
                        "channel_key": "telegram",
                        "identifier_claims": {
                            "identifier_type": "path_token",
                            "identifier_value": "path-token",
                        },
                        "channel_profile_id": None,
                        "route_key": None,
                        "binding_id": None,
                        "client_profile_id": str(_CLIENT_PROFILE_ID),
                        "client_profile_key": "telegram-a",
                        "tenant_resolution": {
                            "mode": "resolved",
                            "reason_code": None,
                            "source": "telegram.ingress_routing",
                        },
                    },
                }
            ],
        )
        logger.debug.assert_any_call("Skip duplicate Telegram message event.")

    async def test_callback_query_auto_ack_and_text_routing_with_context(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"4001": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.telegram_botapi_webhook_event)

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=_make_callback_update(data="btn-1"))),
        ):
            response = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, {"response": "OK"})
        client.answer_callback_query.assert_any_await(callback_query_id="cq-1")
        messaging_service.handle_text_message.assert_awaited_once_with(
            "telegram",
            room_id="3001",
            sender="4001",
            message="btn-1",
            message_context=[
                {
                    "type": "telegram_callback",
                    "content": {
                        "callback_query_id": "cq-1",
                        "callback_data": "btn-1",
                    },
                },
                {
                    "type": "ingress_route",
                    "content": {
                        "tenant_id": "11111111-1111-1111-1111-111111111111",
                        "tenant_slug": "tenant-a",
                        "platform": "telegram",
                        "channel_key": "telegram",
                        "identifier_claims": {
                            "identifier_type": "path_token",
                            "identifier_value": "path-token",
                        },
                        "channel_profile_id": None,
                        "route_key": None,
                        "binding_id": None,
                        "client_profile_id": str(_CLIENT_PROFILE_ID),
                        "client_profile_key": "telegram-a",
                        "tenant_resolution": {
                            "mode": "resolved",
                            "reason_code": None,
                            "source": "telegram.ingress_routing",
                        },
                    },
                },
            ],
        )

    async def test_media_update_triggers_download_and_audio_handler_routing(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"4001": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.telegram_botapi_webhook_event)

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=_make_audio_update(file_id="audio-123"))),
        ):
            response = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, {"response": "OK"})
        client.download_media.assert_awaited_once_with("audio-123")
        messaging_service.handle_audio_message.assert_awaited_once()
        routed_message = messaging_service.handle_audio_message.await_args.kwargs["message"]
        self.assertEqual(routed_message["file"], "/tmp/file.bin")

    async def test_processing_failure_is_persisted_to_dead_letter(self) -> None:
        logger = Mock()
        relational_gateway = _MemoryRelational()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(side_effect=RuntimeError("boom")),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(return_value={"4001": "Known User"}),
            add_known_user=AsyncMock(),
        )
        client = _make_client()

        ipc_ext = _new_extension(
            logger=logger,
            relational_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            client=client,
        )
        ipc_service = _new_ipc_service(logger=logger, ipc_ext=ipc_ext)
        endpoint = unwrap(webhook.telegram_botapi_webhook_event)

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=_make_text_update(text="explode"))),
        ):
            response = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, {"response": "OK"})
        self.assertEqual(len(relational_gateway.dead_letters), 1)
        self.assertEqual(
            relational_gateway.dead_letters[0]["reason_code"],
            "processing_exception",
        )
