"""Reliability E2E tests for WhatsApp webhook processing."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from sqlalchemy.exc import IntegrityError

from mugen.core.client.whatsapp import DefaultWhatsAppClient
from mugen.core.contract.service.ingress_routing import (
    IngressRouteResolution,
    IngressRouteResult,
)
from mugen.core.service.ipc import DefaultIPCService
from mugen.core.plugin.whatsapp.wacapi.api import webhook
from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension

_CLIENT_PROFILE_ID = uuid.UUID("00000000-0000-0000-0000-000000000204")


class _Response:
    def __init__(self, *, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text


class _MemoryRelational:
    def __init__(self) -> None:
        self.event_dedup: dict[tuple[str, str], dict] = {}
        self.dead_letters: list[dict] = []

    async def insert_one(self, table: str, record: dict):
        if table == "whatsapp_wacapi_event_dedup":
            key = (record["event_type"], record["dedupe_key"])
            if key in self.event_dedup:
                raise IntegrityError("insert", {}, Exception("duplicate"))
            self.event_dedup[key] = dict(record)
            return dict(record)
        if table == "whatsapp_wacapi_event_dead_letter":
            self.dead_letters.append(dict(record))
            return dict(record)
        raise ValueError(f"Unsupported table: {table}")

    async def update_one(self, table: str, where: dict, changes: dict):
        if table != "whatsapp_wacapi_event_dedup":
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
            platforms=["whatsapp"],
            runtime=SimpleNamespace(
                profile="platform_full",
                provider_readiness_timeout_seconds=15.0,
                provider_shutdown_timeout_seconds=10.0,
                shutdown_timeout_seconds=60.0,
                phase_b=SimpleNamespace(
                    startup_timeout_seconds=30.0,
                ),
            ),
        ),
        whatsapp=SimpleNamespace(
            user_access=SimpleNamespace(
                mode="allow-all",
                users=[],
                denied_message=None,
            ),
            graphapi=SimpleNamespace(
                base_url="https://graph.example.com",
                version="v19.0",
                access_token="TOKEN_123",
                timeout_seconds=10.0,
                max_download_bytes=20 * 1024 * 1024,
                max_api_retries=1,
                retry_backoff_seconds=0,
            ),
            business=SimpleNamespace(phone_number_id="123456789"),
        ),
    )


def _make_message_event(message_id: str, text: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {
                                    "wa_id": "15551230001",
                                    "profile": {"name": "Known User"},
                                }
                            ],
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": "15551230001",
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


class _IngressRoutingStub:
    async def resolve(self, request) -> IngressRouteResolution:
        identifier_value = request.identifier_value
        if not isinstance(identifier_value, str) or identifier_value.strip() == "":
            identifier_value = "123456789"
        return IngressRouteResolution(
            ok=True,
            result=IngressRouteResult(
                tenant_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
                tenant_slug="tenant-a",
                platform="whatsapp",
                channel_key="whatsapp",
                client_profile_id=_CLIENT_PROFILE_ID,
                client_profile_key="whatsapp-a",
                identifier_claims={
                    "identifier_type": "phone_number_id",
                    "identifier_value": str(identifier_value),
                },
            ),
        )


class TestMugenWhatsAppReliabilityE2E(unittest.IsolatedAsyncioTestCase):
    """Exercises duplicate webhook handling and transient retry recovery."""

    async def test_duplicate_webhook_deliveries_are_processed_once(self) -> None:
        config = _make_config()
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
            get_known_users_list=AsyncMock(
                return_value={"15551230001": "Known User"}
            ),
            add_known_user=AsyncMock(),
        )
        client = SimpleNamespace(
            send_text_message=AsyncMock(return_value={"ok": True, "data": {}}),
        )
        ipc_ext = WhatsAppWACAPIIPCExtension(
            config=config,
            logging_gateway=logger,
            relational_storage_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            whatsapp_client=client,
            ingress_routing_service=_IngressRoutingStub(),
        )
        ipc_service = DefaultIPCService(
            config=SimpleNamespace(),
            logging_gateway=logger,
        )
        ipc_service.bind_ipc_extension(ipc_ext)
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        payload = _make_message_event("wamid-dup-1", "hello")

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            first = await endpoint(
                path_token="whatsapp-path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            second = await endpoint(
                path_token="whatsapp-path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(first, {"response": "OK"})
        self.assertEqual(second, {"response": "OK"})
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "15551230001")
        self.assertEqual(kwargs["sender"], "15551230001")
        self.assertEqual(kwargs["message"], "hello")
        ingress_route = kwargs["message_context"][-1]["content"]
        self.assertEqual(ingress_route["platform"], "whatsapp")
        self.assertEqual(ingress_route["client_profile_id"], str(_CLIENT_PROFILE_ID))
        self.assertEqual(ingress_route["client_profile_key"], "whatsapp-a")
        logger.debug.assert_any_call("Skip duplicate WhatsApp message event.")

    async def test_transient_graph_failure_recovers_via_retry(self) -> None:
        config = _make_config()
        config.whatsapp.graphapi.typing_indicator_enabled = False
        relational_gateway = _MemoryRelational()
        ext_logger = Mock()
        client_logger = Mock()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(
                return_value=[{"type": "text", "content": "response"}]
            ),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=AsyncMock(
                return_value={"15551230001": "Known User"}
            ),
            add_known_user=AsyncMock(),
        )

        whatsapp_client = DefaultWhatsAppClient(
            config=config,
            ipc_service=Mock(),
            keyval_storage_gateway=Mock(),
            logging_gateway=client_logger,
            messaging_service=messaging_service,
            user_service=user_service,
        )
        session = Mock()
        session.closed = False
        session.post = AsyncMock(
            side_effect=[
                _Response(status=503, text='{"error":"temporary"}'),
                _Response(
                    status=200,
                    text='{"messages":[{"id":"wamid-response-1"}]}',
                ),
            ]
        )
        whatsapp_client._client_session = session  # pylint: disable=protected-access

        ipc_ext = WhatsAppWACAPIIPCExtension(
            config=config,
            logging_gateway=ext_logger,
            relational_storage_gateway=relational_gateway,
            messaging_service=messaging_service,
            user_service=user_service,
            whatsapp_client=whatsapp_client,
            ingress_routing_service=_IngressRoutingStub(),
        )
        ipc_service = DefaultIPCService(
            config=SimpleNamespace(),
            logging_gateway=ext_logger,
        )
        ipc_service.bind_ipc_extension(ipc_ext)
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        payload = _make_message_event("wamid-retry-1", "hello")

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            response = await endpoint(
                path_token="whatsapp-path-token",
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: ext_logger,
            )

        self.assertEqual(response, {"response": "OK"})
        self.assertEqual(session.post.await_count, 2)
        kwargs = messaging_service.handle_text_message.await_args.kwargs
        self.assertEqual(kwargs["room_id"], "15551230001")
        self.assertEqual(kwargs["sender"], "15551230001")
        self.assertEqual(kwargs["message"], "hello")
        ingress_route = kwargs["message_context"][-1]["content"]
        self.assertEqual(ingress_route["client_profile_id"], str(_CLIENT_PROFILE_ID))
        self.assertEqual(ingress_route["client_profile_key"], "whatsapp-a")
