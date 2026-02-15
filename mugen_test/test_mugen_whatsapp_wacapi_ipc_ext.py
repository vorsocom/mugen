"""Unit tests for mugen.core.plugin.whatsapp.wacapi.ipc_ext."""

import asyncio
import json
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
            return_value=json.dumps({"url": "https://media.example"})
        ),
        download_media=AsyncMock(return_value="/tmp/file.bin"),
        upload_media=AsyncMock(return_value=json.dumps({"id": "media-id"})),
        send_audio_message=AsyncMock(return_value="{}"),
        send_document_message=AsyncMock(return_value="{}"),
        send_image_message=AsyncMock(return_value="{}"),
        send_text_message=AsyncMock(return_value="{}"),
        send_video_message=AsyncMock(return_value="{}"),
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

    async def test_parse_json_dict_handles_missing_invalid_and_non_dict(self) -> None:
        logging_gateway = Mock()
        ext = _new_extension(
            config=_make_config(beta_active=False),
            logging_gateway=logging_gateway,
        )

        self.assertIsNone(ext._parse_json_dict(None, "ctx"))  # pylint: disable=protected-access
        self.assertIsNone(
            ext._parse_json_dict("{not-json}", "ctx")  # pylint: disable=protected-access
        )
        self.assertIsNone(
            ext._parse_json_dict("[]", "ctx")  # pylint: disable=protected-access
        )

        logging_gateway.error.assert_any_call("Missing payload for ctx.")
        logging_gateway.error.assert_any_call("Invalid JSON payload for ctx.")
        logging_gateway.error.assert_any_call("Unexpected payload type for ctx.")

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
                            return_value=json.dumps({"url": "https://media.example"})
                        )
                        client.download_media = AsyncMock(return_value=None)

                    messaging_service = _make_messaging_service()
                    ext = _new_extension(
                        config=_make_config(beta_active=False),
                        client=client,
                        messaging_service=messaging_service,
                        user_service=_make_user_service(known_users={"15550021": "known"}),
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
                    "type": "interactive",
                    "interactive": {"type": "button_reply"},
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
                "type": "interactive",
                "interactive": {"type": "button_reply"},
            },
            message_type="interactive",
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
                json.dumps({"error": "audio-upload-failed"}),
                json.dumps({"error": "file-upload-failed"}),
                json.dumps({"error": "image-upload-failed"}),
                json.dumps({"error": "video-upload-failed"}),
            ]
        )
        client.send_text_message = AsyncMock(
            return_value=json.dumps({"error": "text-failed"})
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
        logging_gateway.error.assert_any_call("audio-upload-failed")
        logging_gateway.error.assert_any_call("file-upload-failed")
        logging_gateway.error.assert_any_call("image-upload-failed")
        logging_gateway.error.assert_any_call("text-failed")
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
                json.dumps({}),
                json.dumps({}),
                json.dumps({}),
                json.dumps({}),
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
                json.dumps({"id": "audio-id"}),
                json.dumps({"id": "file-id"}),
                json.dumps({"id": "image-id"}),
                json.dumps({"id": "video-id"}),
            ]
        )
        client.send_audio_message = AsyncMock(
            return_value=json.dumps({"error": "audio-send"})
        )
        client.send_document_message = AsyncMock(
            return_value=json.dumps({"error": "file-send"})
        )
        client.send_image_message = AsyncMock(
            return_value=json.dumps({"error": "image-send"})
        )
        client.send_video_message = AsyncMock(
            return_value=json.dumps({"error": "video-send"})
        )
        client.send_text_message = AsyncMock(return_value="{}")
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

        logging_gateway.error.assert_any_call("Send audio to user failed.")
        logging_gateway.error.assert_any_call("audio-send")
        logging_gateway.error.assert_any_call("Send document to user failed.")
        logging_gateway.error.assert_any_call("file-send")
        logging_gateway.error.assert_any_call("Send image to user failed.")
        logging_gateway.error.assert_any_call("image-send")
        logging_gateway.error.assert_any_call("Send video to user failed.")
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

        await ext._wacapi_event({"data": {"entry": []}})  # pylint: disable=protected-access

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
