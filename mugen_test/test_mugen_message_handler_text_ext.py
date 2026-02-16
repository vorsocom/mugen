"""Unit tests for mugen.core.plugin.message_handler.text.mh_ext."""

import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.contract.gateway.completion import CompletionGatewayError
from mugen.core.plugin.message_handler.text.mh_ext import DefaultTextMHExtension


class _MemoryKeyVal:
    def __init__(self):
        self.store = {}

    def has_key(self, key: str) -> bool:
        return key in self.store

    def get(self, key: str, _decode: bool = True):
        return self.store[key]

    def put(self, key: str, value):
        self.store[key] = value


class _BaseExt:
    def __init__(self, supported: bool):
        self._supported = supported

    def platform_supported(self, _platform: str) -> bool:
        return self._supported


class _CommandExt(_BaseExt):
    def __init__(self, supported: bool, commands, response):
        super().__init__(supported)
        self.commands = commands
        self.process_message = AsyncMock(return_value=response)


class _ContextExt(_BaseExt):
    def __init__(self, supported: bool, context):
        super().__init__(supported)
        self.get_context = Mock(return_value=context)


class _RagExt(_BaseExt):
    def __init__(self, supported: bool, rag_context, rag_responses):
        super().__init__(supported)
        self.retrieve = AsyncMock(return_value=(rag_context, rag_responses))


class _RppExt(_BaseExt):
    def __init__(self, supported: bool, response: str):
        super().__init__(supported)
        self.preprocess_response = AsyncMock(return_value=response)


class _CtExt(_BaseExt):
    def __init__(self, supported: bool):
        super().__init__(supported)
        self.process_message = AsyncMock(return_value=None)


def _make_messaging_service(
    *,
    cp_extensions=None,
    ctx_extensions=None,
    rag_extensions=None,
    rpp_extensions=None,
    ct_extensions=None,
):
    return SimpleNamespace(
        cp_extensions=cp_extensions or [],
        ctx_extensions=ctx_extensions or [],
        rag_extensions=rag_extensions or [],
        rpp_extensions=rpp_extensions or [],
        ct_extensions=ct_extensions or [],
    )


def _make_config(debug_conversation: bool) -> SimpleNamespace:
    return SimpleNamespace(mugen=SimpleNamespace(debug_conversation=debug_conversation))


class TestMugenMessageHandlerTextExtension(unittest.IsolatedAsyncioTestCase):
    """Covers command handling and full text-message pipeline behavior."""

    def _new_ext(
        self,
        *,
        completion_result,
        messaging_service,
        keyval,
        debug_conversation: bool,
    ) -> DefaultTextMHExtension:
        completion_gateway = Mock()
        completion_gateway.get_completion = AsyncMock(return_value=completion_result)
        return DefaultTextMHExtension(
            completion_gateway=completion_gateway,
            config=_make_config(debug_conversation),
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
            messaging_service=messaging_service,
        )

    async def test_message_type_and_platform_metadata(self) -> None:
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="ok"),
            messaging_service=_make_messaging_service(),
            keyval=_MemoryKeyVal(),
            debug_conversation=False,
        )
        self.assertEqual(ext.message_types, ["text"])
        self.assertEqual(ext.platforms, [])

    async def test_handle_message_returns_command_response_early(self) -> None:
        keyval = _MemoryKeyVal()
        unsupported_cp = _CommandExt(
            supported=False,
            commands=["/clear"],
            response=[{"type": "text", "content": "ignored"}],
        )
        command_cp = _CommandExt(
            supported=True,
            commands=["/clear"],
            response=[{"type": "text", "content": "Context cleared."}],
        )
        messaging_service = _make_messaging_service(
            cp_extensions=[unsupported_cp, command_cp],
        )
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            messaging_service=messaging_service,
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-1",
            sender="user-1",
            message="/clear",
        )

        self.assertEqual(response, [{"type": "text", "content": "Context cleared."}])
        command_cp.process_message.assert_awaited_once_with(
            "/clear", "room-1", "user-1"
        )
        ext._completion_gateway.get_completion.assert_not_called()

    async def test_handle_message_full_pipeline_with_augmentation_and_none_completion(
        self,
    ) -> None:
        keyval = _MemoryKeyVal()
        keyval.store["chat_history:room-2"] = json.dumps(
            {"messages": [{"role": "assistant", "content": "old"}]}
        )
        ctx_supported = _ContextExt(
            supported=True,
            context=[{"role": "system", "content": "You are a helpful assistant."}],
        )
        ctx_unsupported = _ContextExt(
            supported=False,
            context=[{"role": "system", "content": "ignored"}],
        )
        rag_supported = _RagExt(
            supported=True,
            rag_context=[{"role": "system", "content": "RAG fact"}],
            rag_responses=[{"type": "text", "content": "RAG response"}],
        )
        rag_unsupported = _RagExt(
            supported=False,
            rag_context=[{"role": "system", "content": "ignored"}],
            rag_responses=[{"type": "text", "content": "ignored"}],
        )
        rpp_supported = _RppExt(supported=True, response="preprocessed")
        rpp_unsupported = _RppExt(supported=False, response="ignored")
        ct_supported = _CtExt(supported=True)
        ct_unsupported = _CtExt(supported=False)
        messaging_service = _make_messaging_service(
            ctx_extensions=[ctx_supported, ctx_unsupported],
            rag_extensions=[rag_supported, rag_unsupported],
            rpp_extensions=[rpp_supported, rpp_unsupported],
            ct_extensions=[ct_supported, ct_unsupported],
        )
        ext = self._new_ext(
            completion_result=None,
            messaging_service=messaging_service,
            keyval=keyval,
            debug_conversation=True,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-2",
            sender="user-2",
            message="hello",
            message_context=[{"role": "system", "content": "Attached context"}],
        )

        self.assertEqual(response[0], {"type": "text", "content": "preprocessed"})
        self.assertEqual(response[1], {"type": "text", "content": "RAG response"})
        ext._completion_gateway.get_completion.assert_awaited_once()

        completion_request = ext._completion_gateway.get_completion.await_args.args[0]
        self.assertEqual(completion_request.messages[0].role, "system")
        self.assertIn("[CONTEXT]", completion_request.messages[-1].content)
        self.assertIn("Attached context", completion_request.messages[-1].content)
        self.assertIn("RAG fact", completion_request.messages[-1].content)

        persisted = json.loads(keyval.store["chat_history:room-2"])
        self.assertEqual(persisted["messages"][-1]["content"], "Error")

        rpp_supported.preprocess_response.assert_awaited_once_with(
            "room-2",
            user_id="user-2",
        )
        self.assertEqual(ct_supported.process_message.call_count, 1)

    async def test_handle_message_success_path_and_history_helpers(self) -> None:
        keyval = _MemoryKeyVal()
        non_matching_cp = _CommandExt(
            supported=True,
            commands=["/noop"],
            response=[{"type": "text", "content": "ignored"}],
        )
        matching_none_cp = _CommandExt(
            supported=True,
            commands=["hello"],
            response=None,
        )
        messaging_service = _make_messaging_service(
            cp_extensions=[non_matching_cp, matching_none_cp],
        )
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=messaging_service,
            keyval=keyval,
            debug_conversation=False,
        )

        loaded_history = ext._load_chat_history("room-3")
        self.assertEqual(loaded_history, {"messages": []})
        keyval.store["chat_history:room-3"] = "{"
        self.assertEqual(ext._load_chat_history("room-3"), {"messages": []})
        keyval.store["chat_history:room-3"] = b"\xff"
        self.assertEqual(ext._load_chat_history("room-3"), {"messages": []})
        keyval.store["chat_history:room-3"] = json.dumps(["not-a-dict"])
        self.assertEqual(ext._load_chat_history("room-3"), {"messages": []})

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-3",
            sender="user-3",
            message="hello",
        )

        matching_none_cp.process_message.assert_awaited_once_with(
            "hello",
            "room-3",
            "user-3",
        )
        self.assertEqual(response, [{"type": "text", "content": "assistant answer"}])
        saved = json.loads(keyval.store["chat_history:room-3"])
        self.assertEqual(saved["messages"][0], {"role": "user", "content": "hello"})
        self.assertEqual(
            saved["messages"][-1],
            {"role": "assistant", "content": "assistant answer"},
        )

    async def test_handle_message_logs_ct_extension_errors_without_failing(
        self,
    ) -> None:
        keyval = _MemoryKeyVal()
        failing_ct = _CtExt(supported=True)
        failing_ct.process_message = AsyncMock(side_effect=RuntimeError("boom"))
        messaging_service = _make_messaging_service(ct_extensions=[failing_ct])
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=messaging_service,
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-4",
            sender="user-4",
            message="hello",
        )

        self.assertEqual(response, [{"type": "text", "content": "assistant answer"}])
        ext._logging_gateway.warning.assert_called_once()

    async def test_handle_message_handles_completion_gateway_failures(self) -> None:
        keyval = _MemoryKeyVal()
        messaging_service = _make_messaging_service()
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            messaging_service=messaging_service,
            keyval=keyval,
            debug_conversation=False,
        )

        ext._completion_gateway.get_completion = AsyncMock(
            side_effect=CompletionGatewayError(
                provider="bedrock",
                operation="completion",
                message="failed",
            )
        )
        response = await ext.handle_message(
            platform="matrix",
            room_id="room-5",
            sender="user-5",
            message="hello",
        )
        self.assertEqual(response, [{"type": "text", "content": "Error"}])

        ext._completion_gateway.get_completion = AsyncMock(side_effect=RuntimeError("boom"))
        response = await ext.handle_message(
            platform="matrix",
            room_id="room-6",
            sender="user-6",
            message="hello",
        )
        self.assertEqual(response, [{"type": "text", "content": "Error"}])
