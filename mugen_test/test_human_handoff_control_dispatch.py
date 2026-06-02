"""Dispatcher tests for human-handoff control responses."""

import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.client.matrix import DefaultMatrixClient
from mugen.core.contract.client.web import IWebClient
from mugen.core.plugin.line.messagingapi.ipc_ext import LineMessagingAPIIPCExtension
from mugen.core.plugin.signal.restapi.ipc_ext import SignalRestAPIIPCExtension
from mugen.core.plugin.telegram.botapi.ipc_ext import TelegramBotAPIIPCExtension
from mugen.core.plugin.wechat.ipc_ext import WeChatIPCExtension
from mugen.core.plugin.whatsapp.wacapi.ipc_ext import WhatsAppWACAPIIPCExtension


_CONTROL = {"type": "control", "op": "human_handoff_active"}


class _ConcreteWebClient(IWebClient):
    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def wait_until_stopped(self) -> None:
        return None

    async def enqueue_message(self, **_kwargs):
        return {}

    async def stream_events(self, **_kwargs):
        if False:
            yield ""

    async def resolve_media_download(self, **_kwargs):
        return None


class TestHumanHandoffControlDispatch(unittest.IsolatedAsyncioTestCase):
    """Ensures channel dispatchers do not deliver control responses."""

    async def test_web_contract_default_append_human_reply_raises(self) -> None:
        client = _ConcreteWebClient()

        with self.assertRaises(NotImplementedError):
            await client.append_human_reply(
                conversation_id="conv-1",
                content="hello",
            )

    async def test_line_ignores_control_response(self) -> None:
        ext = object.__new__(LineMessagingAPIIPCExtension)
        ext._line_message_from_response = Mock()
        ext._handle_line_envelope_response = AsyncMock()
        ext._reply_or_push_messages = AsyncMock()

        await ext._dispatch_message_responses(
            responses=[_CONTROL],
            sender="line-user",
            reply_token="reply-token",
        )

        ext._line_message_from_response.assert_not_called()
        ext._handle_line_envelope_response.assert_not_called()
        self.assertEqual(
            ext._reply_or_push_messages.await_args.kwargs["messages"],
            [],
        )

    async def test_telegram_ignores_control_response(self) -> None:
        ext = object.__new__(TelegramBotAPIIPCExtension)
        ext._client = Mock(send_text_message=AsyncMock())
        ext._logging_gateway = Mock()

        await ext._send_response_to_user(_CONTROL, "chat-1")

        ext._client.send_text_message.assert_not_awaited()

    async def test_signal_ignores_control_response(self) -> None:
        ext = object.__new__(SignalRestAPIIPCExtension)
        ext._client = Mock(send_text_message=AsyncMock())
        ext._logging_gateway = Mock()

        await ext._send_response_to_user(_CONTROL, "signal-user")

        ext._client.send_text_message.assert_not_awaited()

    async def test_whatsapp_ignores_control_response(self) -> None:
        ext = object.__new__(WhatsAppWACAPIIPCExtension)
        ext._client = Mock(send_text_message=AsyncMock())
        ext._logging_gateway = Mock()

        await ext._send_response_to_user(_CONTROL, "whatsapp-user")

        ext._client.send_text_message.assert_not_awaited()

    async def test_wechat_ignores_control_response(self) -> None:
        ext = object.__new__(WeChatIPCExtension)
        ext._client = Mock(send_text_message=AsyncMock())
        ext._logging_gateway = Mock()

        await ext._send_response_to_user(_CONTROL, "wechat-user")

        ext._client.send_text_message.assert_not_awaited()

    async def test_matrix_ignores_control_response(self) -> None:
        client = object.__new__(DefaultMatrixClient)
        client._logging_gateway = Mock()
        client._send_audio_message = AsyncMock()
        client._send_file_message = AsyncMock()
        client._send_image_message = AsyncMock()
        client._send_text_message = AsyncMock()
        client._send_video_message = AsyncMock()

        await client._process_message_responses("room-1", [_CONTROL])

        client._send_audio_message.assert_not_awaited()
        client._send_file_message.assert_not_awaited()
        client._send_image_message.assert_not_awaited()
        client._send_text_message.assert_not_awaited()
        client._send_video_message.assert_not_awaited()
