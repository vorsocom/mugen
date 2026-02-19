"""Unit tests for mugen.core.plugin.message_handler.text.mh_ext."""

import asyncio
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
    def __init__(self, supported: bool, commands, response=None, side_effect=None):
        super().__init__(supported)
        self.commands = commands
        self.process_message = AsyncMock(return_value=response, side_effect=side_effect)


class _ContextExt(_BaseExt):
    def __init__(self, supported: bool, context=None, side_effect=None):
        super().__init__(supported)
        if side_effect is not None:
            self.get_context = Mock(side_effect=side_effect)
        else:
            self.get_context = Mock(return_value=context)


class _RagExt(_BaseExt):
    def __init__(self, supported: bool, rag_context=None, rag_responses=None, side_effect=None):
        super().__init__(supported)
        if side_effect is not None:
            self.retrieve = AsyncMock(side_effect=side_effect)
        else:
            self.retrieve = AsyncMock(return_value=(rag_context, rag_responses))


class _RppExt(_BaseExt):
    def __init__(self, supported: bool, response: str | None = None, side_effect=None):
        super().__init__(supported)
        if side_effect is not None:
            self.preprocess_response = AsyncMock(side_effect=side_effect)
        else:
            self.preprocess_response = AsyncMock(return_value=response)


class _LegacyRppExt(_BaseExt):
    def __init__(self, supported: bool, response: str):
        super().__init__(supported)
        self._response = response
        self.calls: list[tuple[str, str]] = []

    async def preprocess_response(self, room_id: str, user_id: str) -> str:
        self.calls.append((room_id, user_id))
        return self._response


class _CtExt(_BaseExt):
    def __init__(self, supported: bool, triggers=None, side_effect=None):
        super().__init__(supported)
        self.triggers = triggers if triggers is not None else []
        self.process_message = AsyncMock(return_value=None, side_effect=side_effect)


# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
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


# pylint: disable=too-many-arguments
# pylint: disable=too-many-positional-arguments
def _make_config(
    *,
    debug_conversation: bool,
    history_max_messages: int = 40,
    extension_timeout_seconds: float = 10.0,
    ct_trigger_prefilter_enabled: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        mugen=SimpleNamespace(
            debug_conversation=debug_conversation,
            messaging=SimpleNamespace(
                history_max_messages=history_max_messages,
                extension_timeout_seconds=extension_timeout_seconds,
                ct_trigger_prefilter_enabled=ct_trigger_prefilter_enabled,
            ),
        )
    )


class TestMugenMessageHandlerTextExtension(unittest.IsolatedAsyncioTestCase):
    """Covers command handling and full text-message pipeline behavior."""

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def _new_ext(
        self,
        *,
        completion_result,
        messaging_service,
        keyval,
        debug_conversation: bool,
        completion_side_effect=None,
        history_max_messages: int = 40,
        extension_timeout_seconds: float = 10.0,
        ct_trigger_prefilter_enabled: bool = True,
    ) -> DefaultTextMHExtension:
        completion_gateway = Mock()
        if completion_side_effect is not None:
            completion_gateway.get_completion = AsyncMock(side_effect=completion_side_effect)
        else:
            completion_gateway.get_completion = AsyncMock(return_value=completion_result)

        return DefaultTextMHExtension(
            completion_gateway=completion_gateway,
            config=_make_config(
                debug_conversation=debug_conversation,
                history_max_messages=history_max_messages,
                extension_timeout_seconds=extension_timeout_seconds,
                ct_trigger_prefilter_enabled=ct_trigger_prefilter_enabled,
            ),
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

    async def test_command_path_fail_open_and_early_return(self) -> None:
        keyval = _MemoryKeyVal()
        failing_cp = _CommandExt(
            supported=True,
            commands=["/clear"],
            side_effect=RuntimeError("boom"),
        )
        successful_cp = _CommandExt(
            supported=True,
            commands=["/clear"],
            response=[{"type": "text", "content": "Context cleared."}],
        )
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            messaging_service=_make_messaging_service(
                cp_extensions=[failing_cp, successful_cp],
            ),
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
        ext._completion_gateway.get_completion.assert_not_called()
        ext._logging_gateway.warning.assert_called()

    async def test_augmentation_is_request_only_and_does_not_mutate_persisted_history(
        self,
    ) -> None:
        keyval = _MemoryKeyVal()
        keyval.store["chat_history:room-2"] = json.dumps(
            {"messages": [{"role": "assistant", "content": "old"}]}
        )
        ctx_ext = _ContextExt(
            supported=True,
            context=[{"role": "system", "content": "persona"}],
        )
        rag_ext = _RagExt(
            supported=True,
            rag_context=[{"content": "RAG fact"}],
            rag_responses=[{"type": "text", "content": "RAG response"}],
        )
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(
                ctx_extensions=[ctx_ext],
                rag_extensions=[rag_ext],
            ),
            keyval=keyval,
            debug_conversation=True,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-2",
            sender="user-2",
            message="hello",
            message_context=[{"content": "Attached context"}],
        )

        self.assertEqual(response[0], {"type": "text", "content": "assistant answer"})
        self.assertEqual(response[1], {"type": "text", "content": "RAG response"})

        completion_request = ext._completion_gateway.get_completion.await_args.args[0]
        self.assertEqual(completion_request.messages[-1].role, "user")
        self.assertEqual(completion_request.messages[-1].content, "hello")

        augmented_messages = [
            message
            for message in completion_request.messages
            if message.role == "system"
            and isinstance(message.content, str)
            and "[REFERENCE_CONTEXT]" in message.content
        ]
        self.assertEqual(len(augmented_messages), 1)
        self.assertIn("Attached context", augmented_messages[0].content)
        self.assertIn("RAG fact", augmented_messages[0].content)

        persisted = json.loads(keyval.store["chat_history:room-2"])
        self.assertEqual(persisted["messages"][-2], {"role": "user", "content": "hello"})
        self.assertEqual(
            persisted["messages"][-1],
            {"role": "assistant", "content": "assistant answer"},
        )

    async def test_completion_failure_returns_error_without_persisting(self) -> None:
        keyval = _MemoryKeyVal()
        initial_history = {
            "messages": [{"role": "assistant", "content": "existing"}],
        }
        keyval.store["chat_history:room-3"] = json.dumps(initial_history)

        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            completion_side_effect=CompletionGatewayError(
                provider="bedrock",
                operation="completion",
                message="failed",
            ),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-3",
            sender="user-3",
            message="hello",
        )

        self.assertEqual(
            response,
            [{"type": "text", "content": ext._completion_error_message}],
        )
        self.assertEqual(
            keyval.store["chat_history:room-3"],
            json.dumps(initial_history),
        )

    async def test_malformed_message_context_and_rag_payloads_are_skipped(self) -> None:
        keyval = _MemoryKeyVal()
        rag_ext = _RagExt(
            supported=True,
            rag_context=[
                "bad",
                {"missing": "content"},
                {"content": "rag-one"},
                {"content": {"rag": "two"}},
            ],
            rag_responses=[{"type": "text", "content": "rag-response"}, "bad"],
        )
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(rag_extensions=[rag_ext]),
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-4",
            sender="user-4",
            message="hello",
            message_context=["bad", {"content": "ctx-one"}, {"x": "missing"}],
        )

        self.assertEqual(response[0], {"type": "text", "content": "assistant answer"})
        self.assertEqual(response[1], {"type": "text", "content": "rag-response"})

        completion_request = ext._completion_gateway.get_completion.await_args.args[0]
        augmented_message = [
            message
            for message in completion_request.messages
            if message.role == "system"
            and isinstance(message.content, str)
            and "[REFERENCE_CONTEXT]" in message.content
        ][0]
        self.assertIn("ctx-one", augmented_message.content)
        self.assertIn("rag-one", augmented_message.content)
        self.assertIn('"rag": "two"', augmented_message.content)

    async def test_extension_failures_and_timeouts_are_fail_open(self) -> None:
        keyval = _MemoryKeyVal()

        async def _slow_rag(_sender, _message, _chat_history):
            await asyncio.sleep(0.05)
            return ([{"content": "ignored"}], [])

        failing_ctx = _ContextExt(
            supported=True,
            side_effect=RuntimeError("ctx-failure"),
        )
        slow_rag = _RagExt(
            supported=True,
            side_effect=_slow_rag,
        )
        failing_rpp = _RppExt(supported=True, side_effect=RuntimeError("rpp-failure"))
        failing_ct = _CtExt(
            supported=True,
            triggers=[],
            side_effect=RuntimeError("ct-failure"),
        )

        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(
                ctx_extensions=[failing_ctx],
                rag_extensions=[slow_rag],
                rpp_extensions=[failing_rpp],
                ct_extensions=[failing_ct],
            ),
            keyval=keyval,
            debug_conversation=False,
            extension_timeout_seconds=0.01,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-5",
            sender="user-5",
            message="hello",
        )

        self.assertEqual(response, [{"type": "text", "content": "assistant answer"}])
        ext._logging_gateway.warning.assert_called()
        failing_ct.process_message.assert_awaited_once()

    async def test_completion_content_is_serialized_to_text(self) -> None:
        keyval = _MemoryKeyVal()
        completion_payload = {"structured": True}
        ext = self._new_ext(
            completion_result=SimpleNamespace(content=completion_payload),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-6",
            sender="user-6",
            message="hello",
        )

        expected = json.dumps(completion_payload, ensure_ascii=True)
        self.assertEqual(response, [{"type": "text", "content": expected}])

        saved = json.loads(keyval.store["chat_history:room-6"])
        self.assertEqual(saved["messages"][-1], {"role": "assistant", "content": expected})

    async def test_history_trimming_applies_to_context_and_persistence(self) -> None:
        keyval = _MemoryKeyVal()
        keyval.store["chat_history:room-7"] = json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "u1"},
                    {"role": "assistant", "content": "a1"},
                    {"role": "user", "content": "u2"},
                    {"role": "assistant", "content": "a2"},
                    {"role": "user", "content": "u3"},
                    {"role": "assistant", "content": "a3"},
                ]
            }
        )
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
            history_max_messages=4,
        )

        await ext.handle_message(
            platform="matrix",
            room_id="room-7",
            sender="user-7",
            message="hello",
        )

        completion_request = ext._completion_gateway.get_completion.await_args.args[0]
        thread_messages = [
            message
            for message in completion_request.messages
            if message.role in {"user", "assistant"}
        ]
        self.assertEqual(len(thread_messages), 5)

        saved = json.loads(keyval.store["chat_history:room-7"])
        self.assertEqual(len(saved["messages"]), 4)
        self.assertEqual(saved["messages"][-1], {"role": "assistant", "content": "assistant answer"})

    async def test_room_lock_prevents_concurrent_history_loss(self) -> None:
        keyval = _MemoryKeyVal()

        async def _completion_side_effect(request):
            await asyncio.sleep(0.01)
            user_message = request.messages[-1].content
            return SimpleNamespace(content=f"assistant:{user_message}")

        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            completion_side_effect=_completion_side_effect,
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        await asyncio.gather(
            ext.handle_message(
                platform="matrix",
                room_id="room-8",
                sender="user-8",
                message="one",
            ),
            ext.handle_message(
                platform="matrix",
                room_id="room-8",
                sender="user-8",
                message="two",
            ),
        )

        saved = json.loads(keyval.store["chat_history:room-8"])
        self.assertEqual(len(saved["messages"]), 4)
        self.assertEqual(
            sorted(item["content"] for item in saved["messages"] if item["role"] == "user"),
            ["one", "two"],
        )
        self.assertEqual(
            sorted(
                item["content"]
                for item in saved["messages"]
                if item["role"] == "assistant"
            ),
            ["assistant:one", "assistant:two"],
        )

    async def test_ct_trigger_prefilter_enabled(self) -> None:
        keyval = _MemoryKeyVal()
        ct_matching = _CtExt(supported=True, triggers=["urgent"])
        ct_not_matching = _CtExt(supported=True, triggers=["billing"])
        ct_empty = _CtExt(supported=True, triggers=[])
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="Need URGENT support"),
            messaging_service=_make_messaging_service(
                ct_extensions=[ct_matching, ct_not_matching, ct_empty],
            ),
            keyval=keyval,
            debug_conversation=False,
            ct_trigger_prefilter_enabled=True,
        )

        await ext.handle_message(
            platform="matrix",
            room_id="room-9",
            sender="user-9",
            message="hello",
        )

        ct_matching.process_message.assert_awaited_once()
        ct_not_matching.process_message.assert_not_awaited()
        ct_empty.process_message.assert_awaited_once()

    async def test_ct_trigger_prefilter_disabled(self) -> None:
        keyval = _MemoryKeyVal()
        ct_matching = _CtExt(supported=True, triggers=["urgent"])
        ct_not_matching = _CtExt(supported=True, triggers=["billing"])
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="Need URGENT support"),
            messaging_service=_make_messaging_service(
                ct_extensions=[ct_matching, ct_not_matching],
            ),
            keyval=keyval,
            debug_conversation=False,
            ct_trigger_prefilter_enabled=False,
        )

        await ext.handle_message(
            platform="matrix",
            room_id="room-10",
            sender="user-10",
            message="hello",
        )

        ct_matching.process_message.assert_awaited_once()
        ct_not_matching.process_message.assert_awaited_once()

    async def test_rpp_supports_new_and_legacy_signatures(self) -> None:
        keyval = _MemoryKeyVal()
        new_rpp = _RppExt(supported=True, response="new-response")
        legacy_rpp = _LegacyRppExt(supported=True, response="legacy-response")
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(
                rpp_extensions=[new_rpp, legacy_rpp],
            ),
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-11",
            sender="user-11",
            message="hello",
        )

        self.assertEqual(response, [{"type": "text", "content": "legacy-response"}])
        new_rpp.preprocess_response.assert_awaited_once_with(
            room_id="room-11",
            user_id="user-11",
            assistant_response="assistant answer",
        )
        self.assertEqual(legacy_rpp.calls, [("room-11", "user-11")])

    async def test_handle_message_skips_unsupported_and_non_matching_command_extensions(
        self,
    ) -> None:
        keyval = _MemoryKeyVal()
        unsupported_cp = _CommandExt(supported=False, commands=["/noop"])
        cp_with_invalid_commands = _CommandExt(supported=True, commands=["/noop"])
        cp_with_invalid_commands.commands = "not-a-list"
        non_matching_cp = _CommandExt(supported=True, commands=["/noop"])
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(
                cp_extensions=[unsupported_cp, cp_with_invalid_commands, non_matching_cp],
            ),
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-12",
            sender="user-12",
            message="hello",
        )

        self.assertEqual(response, [{"type": "text", "content": "assistant answer"}])
        unsupported_cp.process_message.assert_not_awaited()
        cp_with_invalid_commands.process_message.assert_not_awaited()
        non_matching_cp.process_message.assert_not_awaited()

    async def test_collectors_skip_unsupported_extensions_and_bad_rag_payload(self) -> None:
        keyval = _MemoryKeyVal()
        unsupported_ctx = _ContextExt(
            supported=False,
            context=[{"role": "system", "content": "ignored"}],
        )
        unsupported_rag = _RagExt(
            supported=False,
            rag_context=[{"content": "ignored"}],
            rag_responses=[{"type": "text", "content": "ignored"}],
        )
        bad_rag = _RagExt(supported=True, rag_context=[], rag_responses=[])
        bad_rag.retrieve = AsyncMock(return_value={"bad": "payload"})
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(
                ctx_extensions=[unsupported_ctx],
                rag_extensions=[unsupported_rag, bad_rag],
            ),
            keyval=keyval,
            debug_conversation=False,
        )

        context_messages = await ext._collect_context_messages("matrix", "user-13")
        rag_data, rag_responses = await ext._collect_rag_data(
            platform="matrix",
            sender="user-13",
            message="hello",
            chat_history={"messages": []},
        )

        self.assertEqual(context_messages, [])
        self.assertEqual(rag_data, [])
        self.assertEqual(rag_responses, [])
        ext._logging_gateway.warning.assert_called()

    async def test_handle_message_with_no_completion_request_still_runs_post_processing(
        self,
    ) -> None:
        keyval = _MemoryKeyVal()
        rpp_ext = _RppExt(supported=True, response="rpp-response")
        ct_ext = _CtExt(supported=True, triggers=[])
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            messaging_service=_make_messaging_service(
                rpp_extensions=[rpp_ext],
                ct_extensions=[ct_ext],
            ),
            keyval=keyval,
            debug_conversation=False,
        )
        ext._build_completion_request = Mock(return_value=None)

        response = await ext.handle_message(
            platform="matrix",
            room_id="room-13",
            sender="user-13",
            message="hello",
        )

        self.assertEqual(response[0]["content"], "rpp-response")
        self.assertNotIn("chat_history:room-13", keyval.store)
        ct_ext.process_message.assert_awaited_once()

    async def test_get_completion_response_handles_generic_failure(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            completion_side_effect=RuntimeError("boom"),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        completion_request = ext._build_completion_request(
            [{"role": "user", "content": "hello"}]
        )
        response = await ext._get_completion_response(completion_request)

        self.assertIsNone(response)
        ext._logging_gateway.warning.assert_called()

    async def test_get_completion_response_success_does_not_log_full_payload(self) -> None:
        keyval = _MemoryKeyVal()
        completion_result = SimpleNamespace(
            content="assistant response",
            model="gpt-test",
            usage={"total_tokens": 123},
        )
        ext = self._new_ext(
            completion_result=completion_result,
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        completion_request = ext._build_completion_request(
            [{"role": "user", "content": "hello"}]
        )
        response = await ext._get_completion_response(completion_request)

        self.assertIs(response, completion_result)
        ext._logging_gateway.debug.assert_called_once_with("Get completion.")

    async def test_handle_message_logs_full_payload_only_for_blank_assistant_response(
        self,
    ) -> None:
        keyval = _MemoryKeyVal()
        completion_result = SimpleNamespace(
            content=None,
            model="gpt-test",
            usage={"total_tokens": 123},
        )
        ext = self._new_ext(
            completion_result=completion_result,
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        response = await ext.handle_message(
            platform="web",
            room_id="room-blank",
            sender="user-blank",
            message="hello",
        )

        self.assertEqual(response, [{"type": "text", "content": ""}])
        warning_messages = [call.args[0] for call in ext._logging_gateway.warning.call_args_list]
        self.assertTrue(
            any(
                "Assistant response is blank" in message
                and "'No response generated.'" in message
                and "room_id=room-blank" in message
                and '"model": "gpt-test"' in message
                and '"total_tokens": 123' in message
                for message in warning_messages
            )
        )

    async def test_format_completion_response_for_log_branch_coverage(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant response"),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        self.assertEqual(ext._format_completion_response_for_log(None), "null")

        class _ModelDumpOk:
            def model_dump(self):
                return {"model": "ok"}

        class _ModelDumpFail:
            def model_dump(self):
                raise RuntimeError("boom")

            def __str__(self) -> str:
                return "model-dump-failed"

        class _ToDictOk:
            def to_dict(self):
                return {"dict": "ok"}

        class _ToDictFail:
            def to_dict(self):
                raise RuntimeError("boom")

            def __str__(self) -> str:
                return "to-dict-failed"

        class _VarsCarrier:
            pass

        self.assertIn(
            '"model": "ok"',
            ext._format_completion_response_for_log(_ModelDumpOk()),
        )
        self.assertIn(
            "model-dump-failed",
            ext._format_completion_response_for_log(_ModelDumpFail()),
        )
        self.assertIn(
            '"dict": "ok"',
            ext._format_completion_response_for_log(_ToDictOk()),
        )
        self.assertIn(
            "to-dict-failed",
            ext._format_completion_response_for_log(_ToDictFail()),
        )

        vars_carrier = _VarsCarrier()
        vars_carrier.field = "value"
        self.assertIn(
            '"field": "value"',
            ext._format_completion_response_for_log(vars_carrier),
        )

        with patch("builtins.vars", side_effect=TypeError("vars boom")):
            self.assertIn(
                "_VarsCarrier",
                ext._format_completion_response_for_log(_VarsCarrier()),
            )

        with patch("mugen.core.plugin.message_handler.text.mh_ext.json.dumps", side_effect=TypeError("dumps boom")):
            self.assertEqual(
                ext._format_completion_response_for_log({"k": "v"}),
                "{'k': 'v'}",
            )

    async def test_helpers_cover_validation_and_fallback_paths(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        self.assertIsNone(ext._build_completion_request([]))
        self.assertIsNone(ext._build_completion_request([{"role": 1, "content": "x"}]))
        self.assertEqual(
            ext._normalize_response_payload_list(payload="bad", stage="test"),
            [],
        )
        self.assertEqual(
            ext._normalize_completion_message_list("bad", stage="test"),
            [],
        )
        self.assertEqual(
            ext._normalize_completion_message_list(
                [
                    "bad",
                    {"role": 1, "content": "bad-role"},
                    {"role": "user", "content": [{"a": 1}]},
                    {"role": "assistant", "content": [1, 2]},
                ],
                stage="test",
            ),
            [
                {"role": "user", "content": [{"a": 1}]},
                {"role": "assistant", "content": "[1, 2]"},
            ],
        )
        self.assertEqual(ext._normalize_completion_message_content(123), "123")
        self.assertEqual(ext._normalize_augmentation_items(payload="bad", stage="test"), [])

        with unittest.mock.patch(
            "mugen.core.plugin.message_handler.text.mh_ext.json.dumps",
            side_effect=TypeError("bad"),
        ):
            self.assertEqual(ext._coerce_to_text({"a": 1}), "{'a': 1}")
        self.assertEqual(ext._coerce_to_text(None), "")
        self.assertEqual(ext._coerce_to_text(123), "123")

        self.assertTrue(ext._rpp_supports_assistant_response(object()))
        self.assertEqual(
            ext._inject_augmentation_context(
                [{"role": "system", "content": "persona"}],
                ["ctx"],
            )[-1]["role"],
            "system",
        )

    async def test_load_chat_history_and_config_resolution_fallbacks(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="unused"),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
        )

        keyval.store["chat_history:room-14"] = b"\xff"
        self.assertEqual(ext._load_chat_history("room-14"), {"messages": []})

        keyval.store["chat_history:room-14"] = "{"
        self.assertEqual(ext._load_chat_history("room-14"), {"messages": []})

        keyval.store["chat_history:room-14"] = json.dumps(["not-a-dict"])
        self.assertEqual(ext._load_chat_history("room-14"), {"messages": []})

        invalid_cfg_ext = DefaultTextMHExtension(
            completion_gateway=Mock(get_completion=AsyncMock(return_value=None)),
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    debug_conversation=False,
                    messaging=SimpleNamespace(
                        history_max_messages=0,
                        extension_timeout_seconds=0.0,
                        ct_trigger_prefilter_enabled="yes",
                    ),
                )
            ),
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
            messaging_service=_make_messaging_service(),
        )
        self.assertEqual(
            invalid_cfg_ext._history_max_messages,
            invalid_cfg_ext._default_history_max_messages,
        )
        self.assertEqual(
            invalid_cfg_ext._extension_timeout_seconds,
            invalid_cfg_ext._default_extension_timeout_seconds,
        )
        self.assertEqual(
            invalid_cfg_ext._ct_trigger_prefilter_enabled,
            invalid_cfg_ext._default_ct_trigger_prefilter_enabled,
        )

        non_numeric_cfg_ext = DefaultTextMHExtension(
            completion_gateway=Mock(get_completion=AsyncMock(return_value=None)),
            config=SimpleNamespace(
                mugen=SimpleNamespace(
                    debug_conversation=False,
                    messaging=SimpleNamespace(
                        history_max_messages="bad",
                        extension_timeout_seconds="bad",
                        ct_trigger_prefilter_enabled=True,
                    ),
                )
            ),
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
            messaging_service=_make_messaging_service(),
        )
        self.assertEqual(
            non_numeric_cfg_ext._history_max_messages,
            non_numeric_cfg_ext._default_history_max_messages,
        )
        self.assertEqual(
            non_numeric_cfg_ext._extension_timeout_seconds,
            non_numeric_cfg_ext._default_extension_timeout_seconds,
        )

        no_mugen_cfg_ext = DefaultTextMHExtension(
            completion_gateway=Mock(get_completion=AsyncMock(return_value=None)),
            config=SimpleNamespace(),
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
            messaging_service=_make_messaging_service(),
        )
        self.assertFalse(no_mugen_cfg_ext._debug_conversation_enabled())

        no_messaging_cfg_ext = DefaultTextMHExtension(
            completion_gateway=Mock(get_completion=AsyncMock(return_value=None)),
            config=SimpleNamespace(mugen=SimpleNamespace(debug_conversation=False)),
            keyval_storage_gateway=keyval,
            logging_gateway=Mock(),
            messaging_service=_make_messaging_service(),
        )
        self.assertIsInstance(no_messaging_cfg_ext._messaging_config(), SimpleNamespace)

    async def test_extension_timeout_and_trigger_prefilter_edge_cases(self) -> None:
        keyval = _MemoryKeyVal()
        ext = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(),
            keyval=keyval,
            debug_conversation=False,
            extension_timeout_seconds=0.01,
        )

        def _slow_callback(**_kwargs):
            import time

            time.sleep(0.05)
            return [{"role": "system", "content": "ignored"}]

        sync_result = await ext._run_sync_extension_call(
            stage="ctx.get_context",
            ext=SimpleNamespace(),
            callback=_slow_callback,
            user_id="user-15",
        )
        self.assertIsNone(sync_result)

        non_string_trigger_ext = _CtExt(supported=True, triggers=[None, "", "match"])
        self.assertTrue(ext._ct_extension_triggered(non_string_trigger_ext, "this has match"))
        self.assertFalse(
            ext._ct_extension_triggered(non_string_trigger_ext, "this has no token")
        )

        unsupported_rpp = _RppExt(supported=False, response="ignored")
        unsupported_ct = _CtExt(supported=False, triggers=["assistant"])
        ext_with_unsupported = self._new_ext(
            completion_result=SimpleNamespace(content="assistant answer"),
            messaging_service=_make_messaging_service(
                rpp_extensions=[unsupported_rpp],
                ct_extensions=[unsupported_ct],
            ),
            keyval=keyval,
            debug_conversation=False,
        )
        response = await ext_with_unsupported.handle_message(
            platform="matrix",
            room_id="room-15",
            sender="user-15",
            message="hello",
        )
        self.assertEqual(response, [{"type": "text", "content": "assistant answer"}])
        unsupported_rpp.preprocess_response.assert_not_awaited()
        unsupported_ct.process_message.assert_not_awaited()
