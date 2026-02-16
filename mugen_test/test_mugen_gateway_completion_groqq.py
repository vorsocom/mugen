"""Unit tests for mugen.core.gateway.completion.groqq.GroqCompletionGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from groq import GroqError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.groqq import GroqCompletionGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        groq=SimpleNamespace(
            api=SimpleNamespace(
                key="gsk_test",
                dict={
                    "completion": {
                        "model": "llama-3.1-8b-instant",
                        "temp": 0.1,
                        "top_p": 0.8,
                    },
                },
            )
        )
    )


class TestMugenGatewayCompletionGroq(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for Groq completion."""

    async def test_get_completion_builds_request_and_returns_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18)
        response_payload = SimpleNamespace(
            model="llama-3.1-8b-instant",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="hello world"),
                )
            ],
            usage=usage,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=response_payload),
                )
            )
        )

        with patch(
            "mugen.core.gateway.completion.groqq.AsyncGroq",
            return_value=api,
        ) as async_groq:
            gateway = GroqCompletionGateway(config, logging_gateway)

        async_groq.assert_called_once_with(api_key="gsk_test")

        response = await gateway.get_completion(
            [{"role": "user", "content": "hello"}],
        )

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)
        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            top_p=0.8,
            stream=False,
        )

    async def test_get_completion_uses_explicit_inference_and_vendor_params(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="llama-3.1-8b-instant",
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content="hello"),
                )
            ],
            usage=None,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=response_payload),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                max_tokens=42,
                temperature=0.8,
                top_p=0.4,
                stop=["<END>"],
            ),
            vendor_params={
                "frequency_penalty": 0.2,
                "presence_penalty": 0.3,
                "response_format": {"type": "json_object"},
                "seed": 123,
                "tool_choice": "none",
                "tools": [{"type": "function"}],
                "user": "u-1",
            },
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.8,
            top_p=0.4,
            stream=False,
            stop=["<END>"],
            max_tokens=42,
            frequency_penalty=0.2,
            presence_penalty=0.3,
            response_format={"type": "json_object"},
            seed=123,
            tool_choice="none",
            tools=[{"type": "function"}],
            user="u-1",
        )

    async def test_get_completion_wraps_groq_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=GroqError("bad request")),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion([{"role": "user", "content": "hello"}])

    async def test_get_completion_rethrows_completion_gateway_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        sentinel = CompletionGatewayError(
            provider="groq",
            operation="completion",
            message="already wrapped",
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=sentinel))
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError) as context:
            await gateway.get_completion([{"role": "user", "content": "hello"}])

        self.assertIs(context.exception, sentinel)

    async def test_get_completion_raises_gateway_error_on_failure(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=RuntimeError("boom")),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion([{"role": "user", "content": "hello"}])

        logging_gateway.warning.assert_called_once()

    def test_resolve_operation_config_validation(self) -> None:
        logging_gateway = Mock()

        missing_cfg = SimpleNamespace(
            groq=SimpleNamespace(api=SimpleNamespace(key="k", dict={}))
        )
        with patch(
            "mugen.core.gateway.completion.groqq.AsyncGroq",
            return_value=Mock(),
        ):
            gateway = GroqCompletionGateway(missing_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

        invalid_cfg = SimpleNamespace(
            groq=SimpleNamespace(api=SimpleNamespace(key="k", dict={"completion": "x"}))
        )
        with patch(
            "mugen.core.gateway.completion.groqq.AsyncGroq",
            return_value=Mock(),
        ):
            gateway = GroqCompletionGateway(invalid_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

        model_missing = SimpleNamespace(
            groq=SimpleNamespace(api=SimpleNamespace(key="k", dict={"completion": {}}))
        )
        with patch(
            "mugen.core.gateway.completion.groqq.AsyncGroq",
            return_value=Mock(),
        ):
            gateway = GroqCompletionGateway(model_missing, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

    def test_usage_from_response_handles_none(self) -> None:
        payload = SimpleNamespace(usage=None)
        usage = GroqCompletionGateway._usage_from_response(payload)
        self.assertIsNone(usage)
