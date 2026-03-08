"""Unit tests for deterministic completion gateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mugen.core.contract.gateway.completion import (
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.deterministic import DeterministicCompletionGateway


def _gateway() -> DeterministicCompletionGateway:
    return DeterministicCompletionGateway(SimpleNamespace(), Mock())


class TestMugenGatewayCompletionDeterministic(unittest.IsolatedAsyncioTestCase):
    """Covers deterministic completion gateway behavior."""

    async def test_check_readiness_is_noop(self) -> None:
        gateway = _gateway()
        await gateway.check_readiness()

    async def test_aclose_is_noop(self) -> None:
        gateway = _gateway()
        self.assertIsNone(await gateway.aclose())

    async def test_get_completion_uses_vendor_override(self) -> None:
        gateway = _gateway()
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"deterministic_content": "override"},
        )

        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "override")
        self.assertEqual(response.model, "deterministic-model")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.message, {"role": "assistant", "content": "override"})
        self.assertEqual(response.usage.input_tokens, 0)
        self.assertEqual(response.usage.output_tokens, 0)
        self.assertEqual(response.usage.total_tokens, 0)
        self.assertEqual(
            response.usage.vendor_fields,
            {"provider": "deterministic"},
        )
        self.assertEqual(
            response.raw,
            {
                "provider": "deterministic",
                "operation": "completion",
                "message_count": 1,
            },
        )

    async def test_get_completion_uses_last_user_string_content(self) -> None:
        gateway = _gateway()
        request = CompletionRequest(
            operation="classification",
            model="explicit-model",
            messages=[
                CompletionMessage(role="system", content="system note"),
                CompletionMessage(role="user", content="first"),
                CompletionMessage(role="assistant", content="assistant"),
                CompletionMessage(role="user", content="second"),
            ],
            inference=CompletionInferenceConfig(),
        )

        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "second")
        self.assertEqual(response.model, "explicit-model")
        self.assertEqual(response.raw["operation"], "classification")
        self.assertEqual(response.raw["message_count"], 4)

    async def test_get_completion_defaults_when_no_user_text(self) -> None:
        gateway = _gateway()
        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage(role="assistant", content="assistant only"),
                CompletionMessage(role="user", content=None),
                CompletionMessage(role="user", content=[]),
            ],
        )

        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "ok")
