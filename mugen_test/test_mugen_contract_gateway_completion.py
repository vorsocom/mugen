"""Unit tests for mugen.core.contract.gateway.completion."""

import unittest

from mugen.core.contract.gateway.completion import (
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)


class TestMugenContractGatewayCompletion(unittest.TestCase):
    """Covers completion contract validation and normalization."""

    def test_completion_message_from_dict_validates_fields(self) -> None:
        message = CompletionMessage.from_dict({"role": "user", "content": "hello"})
        self.assertEqual(message.role, "user")
        self.assertEqual(message.content, "hello")

        with self.assertRaises(ValueError):
            CompletionMessage.from_dict({"role": 1, "content": "hello"})

        with self.assertRaises(ValueError):
            CompletionMessage.from_dict({"role": "user", "content": 2})

    def test_completion_message_from_dict_supports_structured_content(self) -> None:
        dict_message = CompletionMessage.from_dict(
            {"role": "assistant", "content": {"type": "json", "value": {"a": 1}}},
        )
        list_message = CompletionMessage.from_dict(
            {
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "hello"},
                    {"type": "reasoning", "text": "trace"},
                ],
            },
        )
        null_message = CompletionMessage.from_dict(
            {"role": "assistant", "content": None},
        )

        self.assertEqual(dict_message.content["type"], "json")
        self.assertEqual(list_message.content[0]["type"], "output_text")
        self.assertIsNone(null_message.content)

    def test_completion_message_from_dict_rejects_invalid_list_items(self) -> None:
        with self.assertRaises(ValueError):
            CompletionMessage.from_dict(
                {"role": "assistant", "content": ["invalid-item"]},
            )

    def test_completion_request_accepts_typed_message_list(self) -> None:
        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage.from_dict(
                    {"role": "assistant", "content": "hi"}
                )
            ],
        )
        self.assertEqual(request.messages[0].role, "assistant")

    def test_inference_effective_max_tokens_prefers_max_completion_tokens(self) -> None:
        inference = CompletionInferenceConfig(max_completion_tokens=128, max_tokens=32)
        self.assertEqual(inference.effective_max_tokens, 128)

        legacy_only = CompletionInferenceConfig(max_tokens=32)
        self.assertEqual(legacy_only.effective_max_tokens, 32)

        empty = CompletionInferenceConfig()
        self.assertIsNone(empty.effective_max_tokens)

    def test_inference_stream_defaults(self) -> None:
        inference = CompletionInferenceConfig()
        self.assertFalse(inference.stream)
        self.assertEqual(inference.stream_options, {})
