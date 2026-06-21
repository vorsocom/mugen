"""Tests for reasoning-workflow completion contract helpers."""

from __future__ import annotations

import unittest

from mugen.core.contract.gateway.completion import (
    CompletionContinuationState,
    CompletionReasoningConfig,
    CompletionResponse,
    CompletionTool,
    CompletionToolCall,
    CompletionToolResult,
    CompletionUsage,
)
from mugen.core.contract.gateway.completion_workflow import (
    COMPLETION_CONTINUATION_STATE_METADATA_KEY,
    REDACTED_VALUE,
    completion_continuation_state_from_metadata,
    metadata_with_completion_continuation_state,
    normalize_completion_tool_call,
    redact_provider_payload,
    serialize_completion_metadata_for_log,
    serialize_completion_tool_call,
    serialize_continuation_state_for_log,
    serialize_completion_response_for_log,
)


class TestMugenContractGatewayCompletionReasoning(unittest.TestCase):
    """Covers normalized reasoning-workflow contract primitives."""

    def test_reasoning_config_from_dict_and_is_configured(self) -> None:
        config = CompletionReasoningConfig.from_dict(
            {
                "mode": "adaptive",
                "effort": "medium",
                "budget_tokens": "1024",
                "include_encrypted_state": True,
            }
        )

        self.assertEqual(config.mode, "adaptive")
        self.assertEqual(config.effort, "medium")
        self.assertEqual(config.budget_tokens, 1024)
        self.assertTrue(config.include_encrypted_state)
        self.assertEqual(config.visibility, "opaque")
        self.assertTrue(config.is_configured())
        self.assertEqual(
            config.to_dict()["include_encrypted_state"],
            True,
        )
        self.assertFalse(CompletionReasoningConfig.from_dict(None).is_configured())

    def test_reasoning_config_rejects_invalid_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "Reasoning config"):
            CompletionReasoningConfig.from_dict(["bad"])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "mode"):
            CompletionReasoningConfig.from_dict({"mode": 1})
        with self.assertRaisesRegex(ValueError, "effort"):
            CompletionReasoningConfig.from_dict({"effort": 1})
        with self.assertRaisesRegex(ValueError, "visibility"):
            CompletionReasoningConfig.from_dict({"visibility": 1})

    def test_completion_tool_from_dict_supports_parameters_alias(self) -> None:
        tool = CompletionTool.from_dict(
            {
                "type": "function",
                "name": "lookup",
                "description": "Lookup a value.",
                "parameters": {"type": "object"},
                "strict": True,
                "provider_hints": {"openai": {"defer_loading": True}},
            }
        )

        self.assertEqual(tool.name, "lookup")
        self.assertEqual(tool.kind, "function")
        self.assertTrue(tool.strict)
        self.assertEqual(tool.input_schema, {"type": "object"})
        self.assertEqual(
            tool.to_dict()["provider_hints"]["openai"]["defer_loading"], True
        )

        default_tool = CompletionTool.from_dict({"name": "default"})
        self.assertIsNone(default_tool.strict)
        self.assertEqual(default_tool.provider_hints, {})
        self.assertEqual(
            default_tool.input_schema,
            {"type": "object", "properties": {}},
        )

    def test_completion_tool_rejects_invalid_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "Completion tool"):
            CompletionTool.from_dict([])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "name"):
            CompletionTool.from_dict({"name": ""})
        with self.assertRaisesRegex(ValueError, "description"):
            CompletionTool.from_dict({"name": "x", "description": 1})
        with self.assertRaisesRegex(ValueError, "input_schema"):
            CompletionTool.from_dict({"name": "x", "input_schema": []})
        with self.assertRaisesRegex(ValueError, "kind"):
            CompletionTool.from_dict({"name": "x", "kind": ""})
        with self.assertRaisesRegex(ValueError, "provider_hints"):
            CompletionTool.from_dict({"name": "x", "provider_hints": []})

    def test_tool_call_from_common_provider_shapes(self) -> None:
        chat_call = CompletionToolCall.from_dict(
            {
                "id": "call_1",
                "function": {"name": "math", "arguments": '{"a": 1}'},
            }
        )
        responses_call = CompletionToolCall.from_dict(
            {
                "id": "item_1",
                "call_id": "call_2",
                "name": "lookup",
                "arguments": {"id": "42"},
            }
        )
        anthropic_call = CompletionToolCall.from_dict(
            {
                "tool_use_id": "toolu_1",
                "name": "search",
                "input": {"query": "status"},
            }
        )

        self.assertEqual(chat_call.id, "call_1")
        self.assertEqual(chat_call.name, "math")
        self.assertEqual(chat_call.arguments, {"a": 1})
        self.assertEqual(responses_call.id, "call_2")
        self.assertEqual(responses_call.arguments, {"id": "42"})
        self.assertEqual(anthropic_call.id, "toolu_1")
        self.assertEqual(anthropic_call.arguments, {"query": "status"})
        self.assertEqual(chat_call.to_dict()["provider_item"]["id"], "call_1")

    def test_tool_call_from_dict_handles_bad_arguments(self) -> None:
        tool_call = CompletionToolCall.from_dict(
            {"id": 123, "name": "lookup", "arguments": "not-json"}
        )
        blank_arguments = CompletionToolCall.from_dict(
            {"name": "blank", "arguments": " "}
        )
        list_arguments = CompletionToolCall.from_dict(
            {"name": "list", "arguments": "[]"}
        )
        omitted_arguments = CompletionToolCall.from_dict({"name": "omitted"})
        other_arguments = CompletionToolCall.from_dict(
            {"name": "other", "arguments": 1}
        )

        self.assertEqual(tool_call.id, "123")
        self.assertEqual(tool_call.arguments, {})
        self.assertEqual(blank_arguments.arguments, {})
        self.assertEqual(list_arguments.arguments, {})
        self.assertEqual(omitted_arguments.arguments, {})
        self.assertEqual(other_arguments.arguments, {})
        with self.assertRaisesRegex(ValueError, "tool call"):
            CompletionToolCall.from_dict([])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "name"):
            CompletionToolCall.from_dict({"arguments": "{}"})
        self.assertIsNone(normalize_completion_tool_call({"arguments": "{}"}))
        self.assertIsNone(normalize_completion_tool_call("bad"))

    def test_tool_result_from_dict(self) -> None:
        result = CompletionToolResult.from_dict(
            {
                "call_id": "call_1",
                "name": 123,
                "content": {"ok": True},
                "is_error": True,
            }
        )

        self.assertEqual(result.tool_call_id, "call_1")
        self.assertEqual(result.name, "123")
        self.assertEqual(result.content, {"ok": True})
        self.assertTrue(result.is_error)
        self.assertEqual(result.to_dict()["tool_call_id"], "call_1")
        nameless_result = CompletionToolResult.from_dict({"tool_call_id": "call_2"})
        self.assertIsNone(nameless_result.name)
        self.assertFalse(nameless_result.is_error)
        with self.assertRaisesRegex(ValueError, "tool result"):
            CompletionToolResult.from_dict([])  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "tool_call_id"):
            CompletionToolResult.from_dict({"content": "x"})

    def test_continuation_state_round_trips_and_redacts(self) -> None:
        state = CompletionContinuationState.from_dict(
            {
                "provider": "anthropic",
                "response_id": 123,
                "conversation_id": "conv_1",
                "output_items": [{"type": "message"}],
                "reasoning_items": [{"encrypted_content": "secret"}],
                "thinking_blocks": [{"type": "thinking", "thinking": "secret"}],
                "redacted_thinking_blocks": [
                    {"type": "redacted_thinking", "data": "secret"}
                ],
                "provider_state": {"previous_response_id": "resp_0"},
            }
        )

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.to_dict()["thinking_blocks"][0]["thinking"], "secret")
        self.assertEqual(state.response_id, "123")
        self.assertEqual(
            state.to_redacted_dict(),
            {
                "provider": "anthropic",
                "response_id": "123",
                "conversation_id": "conv_1",
                "output_item_count": 1,
                "reasoning_item_count": 1,
                "thinking_block_count": 1,
                "redacted_thinking_block_count": 1,
                "provider_state_keys": ["previous_response_id"],
            },
        )
        self.assertIsNone(CompletionContinuationState.from_dict(None))
        self.assertEqual(
            serialize_continuation_state_for_log(state.to_dict())[
                "thinking_block_count"
            ],
            1,
        )
        self.assertEqual(
            serialize_continuation_state_for_log(None),
            None,
        )
        self.assertEqual(
            serialize_continuation_state_for_log("bad"),
            {"provider_state": REDACTED_VALUE},
        )
        with self.assertRaisesRegex(ValueError, "continuation state"):
            CompletionContinuationState.from_dict([])  # type: ignore[arg-type]

    def test_completion_continuation_metadata_helpers_cover_edge_cases(self) -> None:
        state = CompletionContinuationState(
            provider="openai",
            response_id="resp_1",
            reasoning_items=[{"encrypted_content": "secret"}],
        )

        self.assertIsNone(completion_continuation_state_from_metadata(None))
        self.assertIs(
            completion_continuation_state_from_metadata(
                {COMPLETION_CONTINUATION_STATE_METADATA_KEY: state}
            ),
            state,
        )
        self.assertIsNone(
            completion_continuation_state_from_metadata(
                {COMPLETION_CONTINUATION_STATE_METADATA_KEY: {"provider_state": 1}}
            )
        )
        self.assertEqual(
            metadata_with_completion_continuation_state({"trace": "1"}, None),
            {"trace": "1"},
        )
        self.assertEqual(serialize_completion_metadata_for_log(None), {})
        redacted = serialize_completion_metadata_for_log(
            {
                "trace": "1",
                COMPLETION_CONTINUATION_STATE_METADATA_KEY: state.to_dict(),
            }
        )
        self.assertEqual(redacted["trace"], "1")
        self.assertEqual(
            redacted[COMPLETION_CONTINUATION_STATE_METADATA_KEY][
                "reasoning_item_count"
            ],
            1,
        )
        self.assertNotIn(
            "reasoning_items",
            redacted[COMPLETION_CONTINUATION_STATE_METADATA_KEY],
        )

    def test_redact_provider_payload_removes_sensitive_values(self) -> None:
        payload = {
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "secret", "signature": "sig"},
                    {"type": "redacted_thinking", "data": "secret"},
                ]
            },
            "nested": [{"api_key": "secret"}, {"safe": "ok"}],
            "session_token": "secret",
            "client_api_key": "secret",
            "client_secret": "secret",
            "tuple": ({"data": "secret"},),
        }

        redacted = redact_provider_payload(payload)

        self.assertEqual(redacted["message"]["content"][0]["thinking"], REDACTED_VALUE)
        self.assertEqual(redacted["message"]["content"][0]["signature"], REDACTED_VALUE)
        self.assertEqual(redacted["message"]["content"][1]["data"], REDACTED_VALUE)
        self.assertEqual(redacted["nested"][0]["api_key"], REDACTED_VALUE)
        self.assertEqual(redacted["nested"][1]["safe"], "ok")
        self.assertEqual(redacted["session_token"], REDACTED_VALUE)
        self.assertEqual(redacted["client_api_key"], REDACTED_VALUE)
        self.assertEqual(redacted["client_secret"], REDACTED_VALUE)
        self.assertEqual(redacted["tuple"][0]["data"], REDACTED_VALUE)
        self.assertEqual(
            serialize_completion_tool_call("raw"), {"provider_item": "raw"}
        )

    def test_serialize_completion_response_for_log_redacts_state(self) -> None:
        completion = CompletionResponse(
            content="done",
            model="model-1",
            stop_reason="tool_use",
            message={"role": "assistant", "reasoning": "secret"},
            tool_calls=[
                CompletionToolCall(
                    id="call_1",
                    name="lookup",
                    arguments={"id": "42"},
                    provider_item={"signature": "secret"},
                )
            ],
            output_items=[{"type": "message"}],
            reasoning_state=CompletionContinuationState(
                provider="openai",
                response_id="resp_1",
                reasoning_items=[{"encrypted_content": "secret"}],
            ),
            provider_state={"api_key": "secret"},
            usage=CompletionUsage(
                input_tokens=1,
                output_tokens=2,
                total_tokens=3,
                reasoning_tokens=4,
                vendor_fields={"reasoning": "secret"},
            ),
            vendor_fields={"encrypted_content": "secret", "safe": "ok"},
        )

        payload = serialize_completion_response_for_log(completion)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["message"]["reasoning"], REDACTED_VALUE)
        self.assertEqual(
            payload["tool_calls"][0]["provider_item"]["signature"], REDACTED_VALUE
        )
        self.assertEqual(payload["output_item_count"], 1)
        self.assertEqual(payload["reasoning_state"]["reasoning_item_count"], 1)
        self.assertEqual(payload["provider_state"]["api_key"], REDACTED_VALUE)
        self.assertEqual(payload["usage"]["reasoning_tokens"], 4)
        self.assertEqual(payload["usage"]["vendor_fields"]["reasoning"], REDACTED_VALUE)
        self.assertEqual(payload["vendor_fields"]["encrypted_content"], REDACTED_VALUE)
        self.assertEqual(payload["vendor_fields"]["safe"], "ok")
        self.assertIsNone(serialize_completion_response_for_log(None))


if __name__ == "__main__":
    unittest.main()
