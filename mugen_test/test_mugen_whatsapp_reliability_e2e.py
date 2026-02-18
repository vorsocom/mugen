"""Reliability E2E tests for WhatsApp webhook processing."""

from inspect import unwrap
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.client.whatsapp import DefaultWhatsAppClient
from mugen.core.plugin.whatsapp.wacapi.api import webhook
from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension


class _Response:
    def __init__(self, *, status: int, text: str) -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text


class _MemoryKeyVal:
    def __init__(self) -> None:
        self.store = {}

    def close(self) -> None:
        return None

    def get(self, key: str, _decode: bool = True):
        return self.store.get(key)

    def has_key(self, key: str) -> bool:
        return key in self.store

    def keys(self) -> list[str]:
        return list(self.store.keys())

    def put(self, key: str, value):
        self.store[key] = value

    def remove(self, key: str):
        return self.store.pop(key, None)


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            beta=SimpleNamespace(
                active=False,
                message="Beta only",
            )
        ),
        whatsapp=SimpleNamespace(
            beta=SimpleNamespace(users=[]),
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


class TestMugenWhatsAppReliabilityE2E(unittest.IsolatedAsyncioTestCase):
    """Exercises duplicate webhook handling and transient retry recovery."""

    async def test_duplicate_webhook_deliveries_are_processed_once(self) -> None:
        config = _make_config()
        logger = Mock()
        keyval = _MemoryKeyVal()
        messaging_service = SimpleNamespace(
            handle_audio_message=AsyncMock(return_value=[]),
            handle_file_message=AsyncMock(return_value=[]),
            handle_image_message=AsyncMock(return_value=[]),
            handle_text_message=AsyncMock(return_value=[]),
            handle_video_message=AsyncMock(return_value=[]),
            mh_extensions=[],
        )
        user_service = SimpleNamespace(
            get_known_users_list=Mock(return_value={"15551230001": "Known User"}),
            add_known_user=Mock(),
        )
        client = SimpleNamespace(
            send_text_message=AsyncMock(return_value={"ok": True, "data": {}}),
        )
        ipc_ext = WhatsAppWACAPIIPCExtension(
            config=config,
            logging_gateway=logger,
            keyval_storage_gateway=keyval,
            messaging_service=messaging_service,
            user_service=user_service,
            whatsapp_client=client,
        )

        async def _handle_ipc_request(platform: str, payload: dict) -> None:
            self.assertEqual(platform, "whatsapp")
            await ipc_ext.process_ipc_command(payload)

        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(side_effect=_handle_ipc_request),
        )
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        payload = _make_message_event("wamid-dup-1", "hello")

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            first = await endpoint(
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            second = await endpoint(
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: logger,
            )

        self.assertEqual(first, {"response": "OK"})
        self.assertEqual(second, {"response": "OK"})
        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15551230001",
            sender="15551230001",
            message="hello",
        )
        logger.debug.assert_any_call("Skip duplicate WhatsApp message event.")

    async def test_transient_graph_failure_recovers_via_retry(self) -> None:
        config = _make_config()
        config.whatsapp.graphapi.typing_indicator_enabled = False
        keyval = _MemoryKeyVal()
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
            get_known_users_list=Mock(return_value={"15551230001": "Known User"}),
            add_known_user=Mock(),
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
            keyval_storage_gateway=keyval,
            messaging_service=messaging_service,
            user_service=user_service,
            whatsapp_client=whatsapp_client,
        )

        async def _handle_ipc_request(platform: str, payload: dict) -> None:
            self.assertEqual(platform, "whatsapp")
            await ipc_ext.process_ipc_command(payload)

        ipc_service = SimpleNamespace(
            handle_ipc_request=AsyncMock(side_effect=_handle_ipc_request),
        )
        endpoint = unwrap(webhook.whatsapp_wacapi_event)
        payload = _make_message_event("wamid-retry-1", "hello")

        with patch.object(
            webhook,
            "request",
            new=SimpleNamespace(get_json=AsyncMock(return_value=payload)),
        ):
            response = await endpoint(
                ipc_provider=lambda: ipc_service,
                logger_provider=lambda: ext_logger,
            )

        self.assertEqual(response, {"response": "OK"})
        self.assertEqual(session.post.await_count, 2)
        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15551230001",
            sender="15551230001",
            message="hello",
        )
