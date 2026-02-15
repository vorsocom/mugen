"""Unit tests for mugen.core.plugin.whatsapp.wacapi.ipc_ext."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension


def _make_config(
    *, beta_active: bool, beta_users=None, beta_message: str = "Beta only"
):
    return SimpleNamespace(
        mugen=SimpleNamespace(
            beta=SimpleNamespace(
                active=beta_active,
                message=beta_message,
            )
        ),
        whatsapp=SimpleNamespace(
            beta=SimpleNamespace(
                users=list(beta_users or []),
            )
        ),
    )


def _make_message_event(message: dict, sender: str = "15550001") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {
                                    "wa_id": sender,
                                    "profile": {"name": "Test User"},
                                }
                            ],
                            "messages": [message],
                        }
                    }
                ]
            }
        ]
    }


def _make_status_event(status: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [status],
                        }
                    }
                ]
            }
        ]
    }


def _make_payload(data: dict, command: str = "whatsapp_wacapi_event") -> dict:
    return {
        "command": command,
        "data": data,
        "response_queue": asyncio.Queue(),
    }


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
        retrieve_media_url=AsyncMock(
            return_value=_ok_payload({"url": "https://media.example"})
        ),
        download_media=AsyncMock(return_value="/tmp/file.bin"),
        upload_media=AsyncMock(return_value=_ok_payload({"id": "media-id"})),
        send_audio_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m1"}]})
        ),
        send_contacts_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m2"}]})
        ),
        send_document_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m3"}]})
        ),
        send_image_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m4"}]})
        ),
        send_interactive_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m5"}]})
        ),
        send_location_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m6"}]})
        ),
        send_reaction_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m7"}]})
        ),
        send_sticker_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m8"}]})
        ),
        send_template_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m9"}]})
        ),
        send_text_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m10"}]})
        ),
        send_video_message=AsyncMock(
            return_value=_ok_payload({"messages": [{"id": "m11"}]})
        ),
    )


def _make_user_service(known_users=None):
    return SimpleNamespace(
        get_known_users_list=Mock(return_value=dict(known_users or {})),
        add_known_user=Mock(),
    )


def _new_extension(
    *,
    config,
    client=None,
    messaging_service=None,
    user_service=None,
    logging_gateway=None,
) -> WhatsAppWACAPIIPCExtension:
    return WhatsAppWACAPIIPCExtension(
        config=config,
        logging_gateway=logging_gateway or Mock(),
        messaging_service=messaging_service or _make_messaging_service(),
        user_service=user_service or _make_user_service(),
        whatsapp_client=client or _make_client(),
    )


class _MhExtension:
    def __init__(self, *, supported: bool, message_types: list[str]):
        self._supported = supported
        self.message_types = message_types
        self.handle_message = AsyncMock(
            return_value=[{"type": "text", "content": "ok"}]
        )

    def platform_supported(self, _platform: str) -> bool:
        return self._supported


class TestMugenWhatsAppWacapiIpcExt(unittest.IsolatedAsyncioTestCase):
    """Covers event routing, media processing, and message-handler fallback paths."""

    async def test_properties_and_process_command_dispatch(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))

        self.assertEqual(ext.platforms, ["whatsapp"])
        self.assertEqual(ext.ipc_commands, ["whatsapp_wacapi_event"])

        with patch.object(ext, "_wacapi_event", new=AsyncMock()) as event_handler:
            await ext.process_ipc_command(
                {"command": "whatsapp_wacapi_event", "data": {}}
            )
            await ext.process_ipc_command({"command": "unknown", "data": {}})

        event_handler.assert_awaited_once()

    async def test_extract_api_data_handles_missing_failed_and_non_dict(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )

        self.assertIsNone(
            ext._extract_api_data(None, "ctx")
        )  # pylint: disable=protected-access
        self.assertIsNone(
            ext._extract_api_data(
                {"ok": False, "error": "boom", "raw": '{"error":"boom"}'}, "ctx"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ext._extract_api_data(
                {"ok": False, "error": "", "raw": ""}, "ctx"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ext._extract_api_data(
                {"ok": True, "data": []}, "ctx"
            )  # pylint: disable=protected-access
        )
        self.assertIsNone(ext._extract_api_data("bad", "ctx"))  # pylint: disable=protected-access
        self.assertEqual(
            ext._extract_api_data({"ok": True, "data": None}, "ctx"), {}
        )  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Missing payload for ctx.")
        logging_gateway.error.assert_any_call("ctx failed.")
        logging_gateway.error.assert_any_call("boom")
        logging_gateway.error.assert_any_call('{"error":"boom"}')
        logging_gateway.error.assert_any_call("Unexpected payload type for ctx.")

    def test_extract_user_text_covers_fallback_and_nfm_paths(self) -> None:
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "button",
                    "button": {"payload": "payload-only"},
                }
            ),
            "payload-only",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn-id"},
                    },
                }
            ),
            "btn-id",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"title": "List title", "id": "list-1"},
                    },
                }
            ),
            "List title",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": "list-only-id"},
                    },
                }
            ),
            "list-only-id",
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {"response_json": {"a": 1}},
                    },
                }
            ),
            '{"a": 1}',
        )
        self.assertEqual(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {"response_json": "{\"a\":1}"},
                    },
                }
            ),
            "{\"a\":1}",
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {"response_json": [1, 2]},
                    },
                }
            )
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "audio",
                }
            )
        )
        self.assertIsNone(
            WhatsAppWACAPIIPCExtension._extract_user_text(
                {
                    "type": "interactive",
                    "interactive": {"type": "unknown"},
                }
            )
        )

    async def test_beta_gate_replies_and_returns_early(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        user_service = _make_user_service()
        ext = _new_extension(
            config=_make_config(beta_active=True, beta_users=["15550002"]),
            client=client,
            messaging_service=messaging_service,
            user_service=user_service,
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-1",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550001",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_text_message.assert_awaited_once_with(
            message="Beta only",
            recipient="15550001",
        )
        self.assertEqual((await payload["response_queue"].get())["response"], "OK")
        messaging_service.handle_text_message.assert_not_awaited()
        user_service.add_known_user.assert_not_called()

    async def test_text_event_processes_and_sends_all_response_types(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {
                    "type": "audio",
                    "file": {"uri": "/tmp/out.ogg", "type": "audio/ogg"},
                },
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/out.pdf",
                        "type": "application/pdf",
                        "name": "out.pdf",
                    },
                },
                {
                    "type": "image",
                    "file": {"uri": "/tmp/out.png", "type": "image/png"},
                },
                {"type": "text", "content": "hello back"},
                {
                    "type": "video",
                    "file": {"uri": "/tmp/out.mp4", "type": "video/mp4"},
                },
            ]
        )
        user_service = _make_user_service(known_users={})
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=user_service,
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-2",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550003",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550003",
            sender="15550003",
            message="incoming",
        )
        user_service.add_known_user.assert_called_once_with(
            "15550003",
            "Test User",
            "15550003",
        )
        self.assertEqual(client.upload_media.await_count, 4)
        client.send_audio_message.assert_awaited_once()
        client.send_document_message.assert_awaited_once()
        client.send_image_message.assert_awaited_once()
        self.assertGreaterEqual(client.send_text_message.await_count, 1)
        client.send_video_message.assert_awaited_once()
        self.assertEqual((await payload["response_queue"].get())["response"], "OK")

    async def test_text_event_processes_extended_response_types(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {
                    "type": "contacts",
                    "contacts": [{"name": {"formatted_name": "A"}}],
                },
                {
                    "type": "location",
                    "location": {"latitude": 59.4, "longitude": 24.7},
                },
                {
                    "type": "interactive",
                    "interactive": {"type": "button", "body": {"text": "Choose"}},
                },
                {
                    "type": "template",
                    "template": {
                        "name": "welcome_template",
                        "language": {"code": "en_US"},
                    },
                },
                {
                    "type": "sticker",
                    "sticker": {"id": "sticker-id"},
                },
                {
                    "type": "reaction",
                    "reaction": {"message_id": "mid-1", "emoji": "👍"},
                },
            ]
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550031": "known"}),
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-extended",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550031",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_contacts_message.assert_awaited_once()
        client.send_location_message.assert_awaited_once()
        client.send_interactive_message.assert_awaited_once()
        client.send_template_message.assert_awaited_once()
        client.send_sticker_message.assert_awaited_once()
        client.send_reaction_message.assert_awaited_once()
        self.assertEqual(client.upload_media.await_count, 0)
        self.assertEqual((await payload["response_queue"].get())["response"], "OK")

    async def test_interactive_and_button_messages_route_to_text_handler(self) -> None:
        cases = [
            (
                {
                    "id": "wamid-i1",
                    "type": "interactive",
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": "btn-1", "title": "Option 1"},
                    },
                },
                "Option 1",
            ),
            (
                {
                    "id": "wamid-i2",
                    "type": "button",
                    "button": {"payload": "payload-2", "text": "Button 2"},
                },
                "Button 2",
            ),
        ]

        for incoming_message, expected_text in cases:
            with self.subTest(expected_text=expected_text):
                client = _make_client()
                messaging_service = _make_messaging_service()
                ext = _new_extension(
                    config=_make_config(beta_active=False),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=_make_user_service(known_users={"15550088": "known"}),
                )
                payload = _make_payload(
                    _make_message_event(
                        incoming_message,
                        sender="15550088",
                    )
                )

                await ext._wacapi_event(payload)  # pylint: disable=protected-access

                messaging_service.handle_text_message.assert_awaited_once_with(
                    "whatsapp",
                    room_id="15550088",
                    sender="15550088",
                    message=expected_text,
                )
                self.assertEqual(
                    (await payload["response_queue"].get())["response"], "OK"
                )

    async def test_button_message_without_extractable_text_delegates_to_handlers(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-button-empty",
                    "type": "button",
                    "button": {},
                },
                sender="15550089",
            )
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={
                "id": "wamid-button-empty",
                "type": "button",
                "button": {},
            },
            message_type="button",
            sender="15550089",
        )

    async def test_upload_response_media_validates_payload_shapes(self) -> None:
        client = _make_client()
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            logging_gateway=logging_gateway,
        )

        self.assertIsNone(
            await ext._upload_response_media({"type": "audio"}, "audio")  # pylint: disable=protected-access
        )
        self.assertIsNone(
            await ext._upload_response_media(  # pylint: disable=protected-access
                {"type": "audio", "file": {"uri": "/tmp/a.ogg"}},
                "audio",
            )
        )
        logging_gateway.error.assert_any_call("Missing file payload for audio response.")
        logging_gateway.error.assert_any_call("Invalid file payload for audio response.")

    async def test_send_response_to_user_handles_validation_and_unknown_types(self) -> None:
        client = _make_client()
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            logging_gateway=logging_gateway,
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {"type": "text", "content": "hello", "reply_to": "mid-1"},
            "15550090",
        )
        client.send_text_message.assert_awaited_with(
            message="hello",
            recipient="15550090",
            reply_to="mid-1",
        )

        invalid_cases = [
            {"type": "text"},
            {"type": "location", "content": "bad"},
            {"type": "interactive", "content": "bad"},
            {"type": "template", "content": "bad"},
            {"type": "sticker", "content": "bad"},
            {"type": "reaction", "content": "bad"},
            {"type": "unknown"},
        ]
        for response in invalid_cases:
            await ext._send_response_to_user(  # pylint: disable=protected-access
                response,
                "15550090",
            )

        logging_gateway.error.assert_any_call("Missing text content in response payload.")
        logging_gateway.error.assert_any_call("Missing location payload in response.")
        logging_gateway.error.assert_any_call(
            "Missing interactive payload in response."
        )
        logging_gateway.error.assert_any_call("Missing template payload in response.")
        logging_gateway.error.assert_any_call("Missing sticker payload in response.")
        logging_gateway.error.assert_any_call("Missing reaction payload in response.")
        logging_gateway.error.assert_any_call("Unsupported response type: unknown.")

    async def test_send_file_response_without_filename(self) -> None:
        client = _make_client()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
        )

        await ext._send_response_to_user(  # pylint: disable=protected-access
            {
                "type": "file",
                "file": {"uri": "/tmp/out.bin", "type": "application/octet-stream"},
            },
            "15550091",
        )

        client.send_document_message.assert_awaited_once_with(
            document={"id": "media-id"},
            recipient="15550091",
            reply_to=None,
        )

    async def test_media_events_route_to_matching_messaging_handlers(self) -> None:
        cases = [
            ("audio", "audio/mpeg", "handle_audio_message"),
            ("document", "application/pdf", "handle_file_message"),
            ("image", "image/png", "handle_image_message"),
            ("video", "video/mp4", "handle_video_message"),
        ]

        for message_type, mime_type, handler_name in cases:
            with self.subTest(message_type=message_type):
                client = _make_client()
                messaging_service = _make_messaging_service()
                user_service = _make_user_service(known_users={"15550004": "known"})
                ext = _new_extension(
                    config=_make_config(beta_active=False),
                    client=client,
                    messaging_service=messaging_service,
                    user_service=user_service,
                )
                payload = _make_payload(
                    _make_message_event(
                        {
                            "id": f"wamid-{message_type}",
                            "type": message_type,
                            message_type: {
                                "id": f"media-{message_type}",
                                "mime_type": mime_type,
                            },
                        },
                        sender="15550004",
                    )
                )

                await ext._wacapi_event(payload)  # pylint: disable=protected-access

                client.retrieve_media_url.assert_awaited_once_with(
                    f"media-{message_type}"
                )
                client.download_media.assert_awaited_once_with(
                    "https://media.example",
                    mime_type,
                )
                getattr(messaging_service, handler_name).assert_awaited_once()
                self.assertEqual(
                    (await payload["response_queue"].get())["response"], "OK"
                )

    async def test_media_events_skip_handlers_when_media_lookup_or_download_missing(
        self,
    ) -> None:
        cases = [
            ("audio", "audio/mpeg", "handle_audio_message"),
            ("document", "application/pdf", "handle_file_message"),
            ("image", "image/png", "handle_image_message"),
            ("video", "video/mp4", "handle_video_message"),
        ]

        for mode in ("missing_url", "missing_download"):
            for message_type, mime_type, handler_name in cases:
                with self.subTest(mode=mode, message_type=message_type):
                    client = _make_client()
                    if mode == "missing_url":
                        client.retrieve_media_url = AsyncMock(return_value=None)
                    else:
                        client.retrieve_media_url = AsyncMock(
                            return_value=_ok_payload({"url": "https://media.example"})
                        )
                        client.download_media = AsyncMock(return_value=None)

                    messaging_service = _make_messaging_service()
                    ext = _new_extension(
                        config=_make_config(beta_active=False),
                        client=client,
                        messaging_service=messaging_service,
                        user_service=_make_user_service(
                            known_users={"15550021": "known"}
                        ),
                    )
                    payload = _make_payload(
                        _make_message_event(
                            {
                                "id": f"wamid-{mode}-{message_type}",
                                "type": message_type,
                                message_type: {
                                    "id": f"media-{message_type}",
                                    "mime_type": mime_type,
                                },
                            },
                            sender="15550021",
                        )
                    )

                    await ext._wacapi_event(payload)  # pylint: disable=protected-access

                    client.retrieve_media_url.assert_awaited_once_with(
                        f"media-{message_type}"
                    )
                    if mode == "missing_url":
                        client.download_media.assert_not_awaited()
                    else:
                        client.download_media.assert_awaited_once_with(
                            "https://media.example",
                            mime_type,
                        )
                    getattr(messaging_service, handler_name).assert_not_awaited()
                    self.assertEqual(
                        (await payload["response_queue"].get())["response"],
                        "OK",
                    )

    async def test_status_event_routes_to_message_handlers(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_payload(
            _make_status_event({"id": "st-1", "status": "delivered"})
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={"id": "st-1", "status": "delivered"},
            message_type="status",
        )
        self.assertEqual((await payload["response_queue"].get())["response"], "OK")

    async def test_event_with_no_messages_or_statuses_still_acknowledges(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_payload(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {},
                            }
                        ]
                    }
                ]
            }
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        self.assertEqual((await payload["response_queue"].get())["response"], "OK")

    async def test_unknown_message_type_delegates_to_message_handlers(self) -> None:
        ext = _new_extension(config=_make_config(beta_active=False))
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-unknown",
                    "type": "unknown",
                    "unknown": {"value": "x"},
                },
                sender="15550010",
            )
        )

        with patch.object(
            ext, "_call_message_handlers", new=AsyncMock()
        ) as route_handlers:
            await ext._wacapi_event(payload)  # pylint: disable=protected-access

        route_handlers.assert_awaited_once_with(
            message={
                "id": "wamid-unknown",
                "type": "unknown",
                "unknown": {"value": "x"},
            },
            message_type="unknown",
            sender="15550010",
        )
        self.assertEqual((await payload["response_queue"].get())["response"], "OK")

    async def test_beta_active_user_in_allow_list_continues_processing(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        ext = _new_extension(
            config=_make_config(beta_active=True, beta_users=["15550011"]),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550011": "known"}),
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-allow",
                    "type": "text",
                    "text": {"body": "hello"},
                },
                sender="15550011",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        messaging_service.handle_text_message.assert_awaited_once_with(
            "whatsapp",
            room_id="15550011",
            sender="15550011",
            message="hello",
        )
        client.send_text_message.assert_not_awaited()

    async def test_response_upload_error_paths_are_logged(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(
            side_effect=[
                _error_payload("audio-upload-failed", status=500),
                _error_payload("file-upload-failed", status=500),
                _error_payload("image-upload-failed", status=500),
                _error_payload("video-upload-failed", status=500),
            ]
        )
        client.send_text_message = AsyncMock(
            return_value=_error_payload("text-failed", status=500)
        )
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "text", "content": "reply"},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550012": "known"}),
            logging_gateway=logging_gateway,
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-upload-error",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550012",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_audio_message.assert_not_awaited()
        client.send_document_message.assert_not_awaited()
        client.send_image_message.assert_not_awaited()
        client.send_video_message.assert_not_awaited()
        logging_gateway.error.assert_any_call("audio upload failed.")
        logging_gateway.error.assert_any_call("audio-upload-failed")
        logging_gateway.error.assert_any_call("document upload failed.")
        logging_gateway.error.assert_any_call("file-upload-failed")
        logging_gateway.error.assert_any_call("image upload failed.")
        logging_gateway.error.assert_any_call("image-upload-failed")
        logging_gateway.error.assert_any_call("text send failed.")
        logging_gateway.error.assert_any_call("text-failed")
        logging_gateway.error.assert_any_call("video upload failed.")
        logging_gateway.error.assert_any_call("video-upload-failed")

    async def test_response_upload_none_payload_skips_send_calls(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(side_effect=[None, None, None, None])
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550014": "known"}),
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-upload-none",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550014",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_audio_message.assert_not_awaited()
        client.send_document_message.assert_not_awaited()
        client.send_image_message.assert_not_awaited()
        client.send_video_message.assert_not_awaited()

    async def test_response_upload_without_id_or_error_skips_send_calls(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(
            side_effect=[
                _ok_payload({}),
                _ok_payload({}),
                _ok_payload({}),
                _ok_payload({}),
            ]
        )
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550015": "known"}),
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-upload-empty",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550015",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        client.send_audio_message.assert_not_awaited()
        client.send_document_message.assert_not_awaited()
        client.send_image_message.assert_not_awaited()
        client.send_video_message.assert_not_awaited()

    async def test_response_send_error_paths_are_logged(self) -> None:
        client = _make_client()
        client.upload_media = AsyncMock(
            side_effect=[
                _ok_payload({"id": "audio-id"}),
                _ok_payload({"id": "file-id"}),
                _ok_payload({"id": "image-id"}),
                _ok_payload({"id": "video-id"}),
            ]
        )
        client.send_audio_message = AsyncMock(
            return_value=_error_payload("audio-send", status=500)
        )
        client.send_document_message = AsyncMock(
            return_value=_error_payload("file-send", status=500)
        )
        client.send_image_message = AsyncMock(
            return_value=_error_payload("image-send", status=500)
        )
        client.send_video_message = AsyncMock(
            return_value=_error_payload("video-send", status=500)
        )
        client.send_text_message = AsyncMock(return_value=_ok_payload({"messages": []}))
        messaging_service = _make_messaging_service()
        messaging_service.handle_text_message = AsyncMock(
            return_value=[
                {"type": "audio", "file": {"uri": "/tmp/a.ogg", "type": "audio/ogg"}},
                {
                    "type": "file",
                    "file": {
                        "uri": "/tmp/f.pdf",
                        "type": "application/pdf",
                        "name": "f.pdf",
                    },
                },
                {"type": "image", "file": {"uri": "/tmp/i.png", "type": "image/png"}},
                {"type": "text", "content": "reply"},
                {"type": "video", "file": {"uri": "/tmp/v.mp4", "type": "video/mp4"}},
            ]
        )
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            user_service=_make_user_service(known_users={"15550013": "known"}),
            logging_gateway=logging_gateway,
        )
        payload = _make_payload(
            _make_message_event(
                {
                    "id": "wamid-send-error",
                    "type": "text",
                    "text": {"body": "incoming"},
                },
                sender="15550013",
            )
        )

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("audio send failed.")
        logging_gateway.error.assert_any_call("audio-send")
        logging_gateway.error.assert_any_call("document send failed.")
        logging_gateway.error.assert_any_call("file-send")
        logging_gateway.error.assert_any_call("image send failed.")
        logging_gateway.error.assert_any_call("image-send")
        logging_gateway.error.assert_any_call("video send failed.")
        logging_gateway.error.assert_any_call("video-send")

    async def test_malformed_event_payload_is_logged_and_acknowledged(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )
        payload = _make_payload({"entry": []})

        await ext._wacapi_event(payload)  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp event payload.")
        self.assertEqual((await payload["response_queue"].get())["response"], "OK")

    async def test_malformed_event_without_response_queue_still_returns(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )

        await ext._wacapi_event(
            {"data": {"entry": []}}
        )  # pylint: disable=protected-access

        logging_gateway.error.assert_any_call("Malformed WhatsApp event payload.")

    async def test_call_message_handlers_supported_and_unsupported_paths(self) -> None:
        client = _make_client()
        messaging_service = _make_messaging_service()
        supported = _MhExtension(supported=True, message_types=["custom"])
        unsupported = _MhExtension(supported=False, message_types=["custom"])
        wrong_type = _MhExtension(supported=True, message_types=["text"])
        messaging_service.mh_extensions = [supported, unsupported, wrong_type]
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            client=client,
            messaging_service=messaging_service,
            logging_gateway=logging_gateway,
        )

        def _create_task(coro):
            coro.close()
            return "task"

        with (
            patch(
                "mugen.core.plugin.whatsapp.wacapi.ipc_ext.asyncio.create_task",
                side_effect=_create_task,
            ) as create_task,
            patch(
                "mugen.core.plugin.whatsapp.wacapi.ipc_ext.asyncio.gather",
                new=AsyncMock(return_value=None),
            ) as gather,
        ):
            await ext._call_message_handlers(  # pylint: disable=protected-access
                message={"id": "m1"},
                message_type="custom",
                sender="15550005",
            )

        supported.handle_message.assert_called_once_with(
            room_id="15550005",
            sender="15550005",
            message={"id": "m1"},
        )
        create_task.assert_called_once()
        gather.assert_called_once_with("task")

        messaging_service.mh_extensions = []
        await ext._call_message_handlers(  # pylint: disable=protected-access
            message={"id": "m2"},
            message_type="unknown",
            sender="15550006",
        )
        logging_gateway.debug.assert_any_call("Unsupported message type: unknown.")
        client.send_text_message.assert_awaited_with(
            message="Unsupported message type..",
            recipient="15550006",
            reply_to="m2",
        )

        client.send_text_message.reset_mock()
        await ext._call_message_handlers(  # pylint: disable=protected-access
            message={"id": "m3"},
            message_type="unknown",
            sender=None,
        )
        client.send_text_message.assert_not_awaited()


def _ok_payload(data: dict | None = None, raw: str = "{}") -> dict:
    return {
        "ok": True,
        "status": 200,
        "data": {} if data is None else data,
        "error": None,
        "raw": raw,
    }


def _error_payload(
    error: str = "error",
    *,
    status: int = 500,
    raw: str = '{"error":"error"}',
) -> dict:
    return {
        "ok": False,
        "status": status,
        "data": None,
        "error": error,
        "raw": raw,
    }
