"""Unit tests for mugen.core.contract.gateway.completion."""

import unittest

from mugen.core.contract.gateway.completion import (
    CompletionMessage,
    CompletionRequest,
    normalise_completion_request,
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

    def test_completion_request_from_context_validates_context_type(self) -> None:
        with self.assertRaises(ValueError):
            CompletionRequest.from_context(context="invalid")  # type: ignore[arg-type]

    def test_normalise_completion_request_handles_both_input_shapes(self) -> None:
        request = CompletionRequest.from_context(
            [{"role": "user", "content": "hello"}],
            operation="completion",
        )
        self.assertIs(normalise_completion_request(request), request)

        converted = normalise_completion_request(
            [{"role": "assistant", "content": "hi"}],
            operation="completion",
        )
        self.assertEqual(converted.messages[0].role, "assistant")
