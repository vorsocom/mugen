"""Reliability E2E tests for LINE webhook + IPC processing."""

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
from mugen.core.plugin.line.messagingapi.api import webhook
from mugen.core.plugin.line.messagingapi.ipc_ext import LineMessagingAPIIPCExtension
from mugen.core.service.ipc import DefaultIPCService


class _MemoryRelational:
    def __init__(self) -> None:
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict):
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

    async def update_one(self, table: str, where: dict, changes: dict):
        if table != "line_messagingapi_event_dedup":
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
            platforms=["line"],
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=10.0,
                shutdown_timeout_seconds=60.0,
                phase_b=SimpleNamespace(startup_timeout_seconds=30.0),
            ),
        ),
        line=SimpleNamespace(
            webhook=SimpleNamespace(
                path_token="path-token",
                dedupe_ttl_seconds=86400,
            ),
            typing=SimpleNamespace(enabled=True),
        ),
    )


def _make_client() -> SimpleNamespace:
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
        get_profile=AsyncMock(return_value={"ok": True, "data": {"displayName": "Known User"}}),
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
                platform="line",
                channel_key="line",
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
) -> LineMessagingAPIIPCExtension:
    return LineMessagingAPIIPCExtension(
        config=_make_config(),
        logging_gateway=logger,
        relational_storage_gateway=relational_gateway,
        messaging_service=messaging_service,
        user_service=user_service,
        line_client=client,
        ingress_routing_service=_IngressRoutingStub(),
    )


def _new_ipc_service(*, logger: Mock, ipc_ext: LineMessagingAPIIPCExtension) -> DefaultIPCService:
    ipc_service = DefaultIPCService(
        config=SimpleNamespace(),
        logging_gateway=logger,
    )
    ipc_service.bind_ipc_extension(ipc_ext)
    return ipc_service


def _make_message_event(*, text: str = "hello") -> dict:
    return {
        "type": "message",
        "webhookEventId": "evt-1001",
        "replyToken": "reply-1001",
        "source": {"type": "user", "userId": "U-1001"},
        "message": {
            "id": "m-1001",
            "type": "text",
            "text": text,
        },
    }


def _make_postback_event(*, data: str = "btn-1") -> dict:
    return {
        "type": "postback",
        "webhookEventId": "evt-1002",
        "replyToken": "reply-1002",
        "source": {"type": "user", "userId": "U-1001"},
        "postback": {
            "data": data,
        },
    }


class TestMugenLineReliabilityE2E(unittest.IsolatedAsyncioTestCase):
    """Exercises dedupe, postback, and dead-letter reliability behavior."""

    async def test_duplicate_delivery_is_processed_once(self) -> None:
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
            get_known_users_list=AsyncMock(return_value={"U-1001": "Known User"}),
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
        endpoint = unwrap(webhook.line_messagingapi_webhook_event)
        payload = {"events": [_make_message_event(text="hello")]}

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
            "line",
            room_id="U-1001",
            sender="U-1001",
            message="hello",
            message_context=[
                {
                    "type": "ingress_route",
                    "content": {
                        "tenant_id": "11111111-1111-1111-1111-111111111111",
                        "tenant_slug": "tenant-a",
                        "platform": "line",
                        "channel_key": "line",
                        "identifier_claims": {
                            "identifier_type": "path_token",
                            "identifier_value": "path-token",
                        },
                        "channel_profile_id": None,
                        "route_key": None,
                        "binding_id": None,
                        "tenant_resolution": {
                            "mode": "resolved",
                            "reason_code": None,
                            "source": "line.ingress_routing",
                        },
                    },
                }
            ],
        )
        logger.debug.assert_any_call("Skip duplicate LINE event type=message.")

    async def test_postback_routes_with_context(self) -> None:
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
            get_known_users_list=AsyncMock(return_value={"U-1001": "Known User"}),
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
        endpoint = unwrap(webhook.line_messagingapi_webhook_event)
        payload = {"events": [_make_postback_event(data="btn-1")]}

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            response = await endpoint(
                path_token="path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(response, {"response": "OK"})
        messaging_service.handle_text_message.assert_awaited_once_with(
            "line",
            room_id="U-1001",
            sender="U-1001",
            message="btn-1",
            message_context=[
                {
                    "type": "line_postback",
                    "content": {
                        "postback": {"data": "btn-1"},
                    },
                },
                {
                    "type": "ingress_route",
                    "content": {
                        "tenant_id": "11111111-1111-1111-1111-111111111111",
                        "tenant_slug": "tenant-a",
                        "platform": "line",
                        "channel_key": "line",
                        "identifier_claims": {
                            "identifier_type": "path_token",
                            "identifier_value": "path-token",
                        },
                        "channel_profile_id": None,
                        "route_key": None,
                        "binding_id": None,
                        "tenant_resolution": {
                            "mode": "resolved",
                            "reason_code": None,
                            "source": "line.ingress_routing",
                        },
                    },
                },
            ],
        )

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
            get_known_users_list=AsyncMock(return_value={"U-1001": "Known User"}),
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
        endpoint = unwrap(webhook.line_messagingapi_webhook_event)
        payload = {"events": [_make_message_event(text="boom")]}

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
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
