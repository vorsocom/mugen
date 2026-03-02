"""Unit tests for mugen.core.gateway.completion.openai.OpenAICompletionGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
from typing import Any

from openai import OpenAIError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.openai import OpenAICompletionGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        openai=SimpleNamespace(
            api=SimpleNamespace(
                key="sk_test",
                base_url="https://api.openai.com/v1",
                timeout_seconds="12.5",
                dict={
                    "completion": {
                        "model": "gpt-4o-mini",
                        "temp": 0.1,
                        "top_p": 0.8,
                    },
                },
            )
        )
    )


async def _stream_chunks(chunks: list[Any]):
    for chunk in chunks:
        yield chunk


def _simple_request() -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
    )


class TestMugenGatewayCompletionOpenAI(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for OpenAI completion."""

    async def test_check_readiness_resolves_required_operation_configs(self) -> None:
        config = _make_config()
        config.openai.api.dict["classification"] = dict(config.openai.api.dict["completion"])
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            responses=SimpleNamespace(create=AsyncMock()),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        with patch("mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        await gateway.check_readiness()
        api.models.list.assert_awaited_once_with(limit=1)

    async def test_check_readiness_raises_when_models_list_is_missing(self) -> None:
        config = _make_config()
        config.openai.api.dict["classification"] = dict(config.openai.api.dict["completion"])
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            responses=SimpleNamespace(create=AsyncMock()),
            models=SimpleNamespace(list=None),
        )

        with patch("mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(RuntimeError, "readiness probe unavailable"):
            await gateway.check_readiness()

    async def test_check_readiness_falls_back_when_limit_kwarg_is_unsupported(self) -> None:
        config = _make_config()
        config.openai.api.dict["classification"] = dict(config.openai.api.dict["completion"])
        logging_gateway = Mock()
        calls: list[dict[str, object]] = []

        def _list_models(**kwargs):
            calls.append(dict(kwargs))
            if "limit" in kwargs:
                raise TypeError("unexpected keyword argument 'limit'")

            async def _done():
                return SimpleNamespace(data=[])

            return _done()

        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            responses=SimpleNamespace(create=AsyncMock()),
            models=SimpleNamespace(list=_list_models),
        )

        with patch("mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        await gateway.check_readiness()
        self.assertEqual(calls, [{"limit": 1}, {}])

    async def test_check_readiness_uses_default_timeout_when_missing(self) -> None:
        config = _make_config()
        config.openai.api.timeout_seconds = None
        config.openai.api.dict["classification"] = dict(config.openai.api.dict["completion"])
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            responses=SimpleNamespace(create=AsyncMock()),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        wait_for_calls: list[float] = []

        async def _wait_for(awaitable, timeout):
            wait_for_calls.append(float(timeout))
            return await awaitable

        with (
            patch("mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api),
            patch("mugen.core.gateway.completion.openai.asyncio.wait_for", side_effect=_wait_for),
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)
            await gateway.check_readiness()

        self.assertEqual(wait_for_calls, [5.0])

    async def test_check_readiness_uses_default_timeout_when_nonpositive(self) -> None:
        config = _make_config()
        config.openai.api.timeout_seconds = None
        config.openai.api.dict["classification"] = dict(config.openai.api.dict["completion"])
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            responses=SimpleNamespace(create=AsyncMock()),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        wait_for_calls: list[float] = []

        async def _wait_for(awaitable, timeout):
            wait_for_calls.append(float(timeout))
            return await awaitable

        with (
            patch("mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api),
            patch("mugen.core.gateway.completion.openai.asyncio.wait_for", side_effect=_wait_for),
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)
            gateway._timeout_seconds = 0  # pylint: disable=protected-access
            await gateway.check_readiness()

        self.assertEqual(wait_for_calls, [5.0])

    async def test_check_readiness_wraps_probe_failures(self) -> None:
        config = _make_config()
        config.openai.api.dict["classification"] = dict(config.openai.api.dict["completion"])
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            responses=SimpleNamespace(create=AsyncMock()),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        async def _wait_for(awaitable, timeout):
            _ = timeout
            await awaitable
            raise RuntimeError("probe boom")

        with (
            patch("mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api),
            patch("mugen.core.gateway.completion.openai.asyncio.wait_for", side_effect=_wait_for),
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    def test_constructor_builds_client_with_optional_settings(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with patch("mugen.core.gateway.completion.openai.AsyncOpenAI") as async_openai:
            OpenAICompletionGateway(config, logging_gateway)

        async_openai.assert_called_once_with(
            api_key="sk_test",
            base_url="https://api.openai.com/v1",
            timeout=12.5,
        )

    def test_constructor_ignores_invalid_timeout_configuration(self) -> None:
        config = _make_config()
        config.openai.api.timeout_seconds = "bad"
        logging_gateway = Mock()

        with patch("mugen.core.gateway.completion.openai.AsyncOpenAI") as async_openai:
            OpenAICompletionGateway(config, logging_gateway)

        async_openai.assert_called_once_with(
            api_key="sk_test",
            base_url="https://api.openai.com/v1",
        )
        logging_gateway.warning.assert_called_once_with(
            "OpenAICompletionGateway: Invalid timeout_seconds configuration."
        )

    async def test_get_completion_builds_request_and_returns_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        usage = SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            completion_tokens_details={"reasoning_tokens": 2},
        )
        response_payload = SimpleNamespace(
            id="chatcmpl-1",
            object="chat.completion",
            created=123,
            system_fingerprint="fp_1",
            service_tier="default",
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        role="assistant",
                        content="hello world",
                        tool_calls=[],
                    ),
                )
            ],
            usage=usage,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=response_payload),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(
            _simple_request(),
        )

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertEqual(
            response.usage.vendor_fields["completion_tokens_details"][
                "reasoning_tokens"
            ],
            2,
        )
        self.assertEqual(response.message["role"], "assistant")
        self.assertEqual(response.vendor_fields["id"], "chatcmpl-1")
        self.assertEqual(response.vendor_fields["system_fingerprint"], "fp_1")
        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            temperature=0.1,
            top_p=0.8,
            stream=False,
        )

    async def test_get_completion_uses_explicit_inference_and_vendor_params(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="gpt-4o-mini",
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
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                max_completion_tokens=42,
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
                "service_tier": "auto",
                "user": "u-1",
            },
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            temperature=0.8,
            top_p=0.4,
            stream=False,
            stop=["<END>"],
            max_completion_tokens=42,
            frequency_penalty=0.2,
            presence_penalty=0.3,
            response_format={"type": "json_object"},
            seed=123,
            tool_choice="none",
            tools=[{"type": "function"}],
            service_tier="auto",
            user="u-1",
        )

    async def test_get_completion_prefers_max_completion_tokens(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="gpt-4o-mini",
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
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(max_completion_tokens=64),
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            temperature=0.1,
            top_p=0.8,
            stream=False,
            max_completion_tokens=64,
        )

    async def test_get_completion_rejects_removed_legacy_max_tokens_vendor_param(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="gpt-4o-mini",
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
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(max_completion_tokens=64),
            vendor_params={"use_legacy_max_tokens": True},
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Removed legacy vendor param 'use_legacy_max_tokens'",
        ):
            await gateway.get_completion(request)

    async def test_get_completion_uses_inference_stream_fields(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(finish_reason="stop", delta=SimpleNamespace())
                ],
                usage=None,
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                stream=True,
                stream_options={"include_usage": True},
            ),
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            temperature=0.1,
            top_p=0.8,
            stream=True,
            stream_options={"include_usage": True},
        )

    async def test_get_completion_rejects_removed_vendor_stream_override(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": "false"},
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Removed legacy vendor param 'stream'",
        ):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_invalid_vendor_stream_boolean(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": "definitely"},
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Removed legacy vendor param 'stream'",
        ):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_invalid_inference_stream_boolean(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream="definitely"),  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Invalid boolean value for inference.stream",
        ):
            await gateway.get_completion(request)

    async def test_get_completion_uses_operation_token_defaults(self) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["max_completion_tokens"] = "21"
        logging_gateway = Mock()
        payload = SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content="ok")
                )
            ],
            usage=None,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=payload),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)
            await gateway.get_completion(_simple_request())

        _, kwargs = api.chat.completions.create.await_args
        self.assertEqual(kwargs["max_completion_tokens"], 21)

        del config.openai.api.dict["completion"]["max_completion_tokens"]
        config.openai.api.dict["completion"]["max_tokens"] = "17"
        api.chat.completions.create.reset_mock()

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "includes removed legacy key 'max_tokens'",
            ):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_omits_temp_and_top_p_when_not_configured(
        self,
    ) -> None:
        config = SimpleNamespace(
            openai=SimpleNamespace(
                api=SimpleNamespace(
                    key="sk_test",
                    dict={"completion": {"model": "gpt-4o-mini"}},
                )
            )
        )
        logging_gateway = Mock()
        payload = SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content="ok")
                )
            ],
            usage=None,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=payload),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        await gateway.get_completion(_simple_request())

        _, kwargs = api.chat.completions.create.await_args
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)
        self.assertNotIn("stop", kwargs)

    async def test_get_completion_streams_content_tool_calls_and_usage(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                id="chatcmpl-1",
                object="chat.completion.chunk",
                created=100,
                system_fingerprint="fp_1",
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            content="hello ",
                            tool_calls=[
                                1,
                                SimpleNamespace(
                                    id="call_1",
                                    type="function",
                                    function=SimpleNamespace(name="weather"),
                                ),
                            ],
                        ),
                    )
                ],
                usage=None,
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content="world"),
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=3,
                    total_tokens=13,
                ),
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                stream=True,
                stream_options={"include_usage": True},
            ),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.tool_calls[0]["id"], "call_1")
        self.assertEqual(response.usage.total_tokens, 13)
        self.assertEqual(response.vendor_fields["id"], "chatcmpl-1")
        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            temperature=0.1,
            top_p=0.8,
            stream=True,
            stream_options={"include_usage": True},
        )

    async def test_get_completion_stream_preserves_structured_deltas(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(
                            content=[
                                SimpleNamespace(type="output_text", text="hi"),
                                {"type": "reasoning", "text": "trace"},
                            ]
                        ),
                    )
                ],
                usage=None,
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content[0]["type"], "output_text")
        self.assertEqual(
            response.vendor_fields["stream_content_deltas"][1]["type"],
            "reasoning",
        )

    async def test_get_completion_stream_preserves_structured_object_delta(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(
                            content=SimpleNamespace(type="output_text", text="hello"),
                            tool_calls=[1, {"id": "call_1", "type": "function"}],
                        ),
                    )
                ],
                usage=None,
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content[0]["type"], "output_text")
        self.assertEqual(response.tool_calls[0]["id"], "call_1")

    async def test_get_completion_stream_handles_chunk_without_choices(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=2,
                    completion_tokens=1,
                    total_tokens=3,
                ),
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "")
        self.assertEqual(response.usage.total_tokens, 3)

    async def test_get_completion_stream_ignores_unrecognized_delta_content(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content=1),
                    )
                ],
                usage=None,
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "")

    async def test_get_completion_stream_raises_when_no_chunks_are_received(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()

        async def _empty_stream():
            if False:
                yield None

        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_empty_stream())
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(request)

    async def test_get_completion_raises_when_response_has_no_choices(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            model="gpt-4o-mini",
                            choices=[],
                            usage=None,
                        )
                    ),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

    async def test_get_completion_includes_additional_choices_metadata(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        payload = SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="primary"),
                ),
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(content="secondary"),
                ),
            ],
            usage=None,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=payload)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())
        self.assertEqual(
            response.vendor_fields["additional_choices"][0]["finish_reason"],
            "length",
        )

    async def test_get_completion_handles_response_without_payload_dict(self) -> None:
        class _CompletionNoDict:
            __slots__ = ("model", "choices", "usage")

            def __init__(self) -> None:
                self.model = "gpt-4o-mini"
                self.choices = [
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="hello"),
                    )
                ]
                self.usage = None

        config = _make_config()
        logging_gateway = Mock()
        payload = _CompletionNoDict()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=payload)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())
        self.assertEqual(response.content, "hello")
        self.assertEqual(response.vendor_fields, {})

    async def test_get_completion_routes_to_responses_from_operation_surface(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        response_payload = {
            "id": "resp_1",
            "object": "response",
            "created_at": 123,
            "status": "completed",
            "service_tier": "default",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "hello responses"}],
                }
            ],
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
        }
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock(return_value=response_payload)),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())

        self.assertEqual(response.content, "hello responses")
        self.assertEqual(response.usage.input_tokens, 3)
        self.assertEqual(response.vendor_fields["id"], "resp_1")
        self.assertEqual(response.vendor_fields["status"], "completed")
        api.responses.create.assert_awaited_once_with(
            input=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            stream=False,
            temperature=0.1,
            top_p=0.8,
        )
        api.chat.completions.create.assert_not_called()

    async def test_get_completion_vendor_override_can_switch_surface(self) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        chat_payload = SimpleNamespace(
            model="gpt-4o-mini",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content="chat path"),
                )
            ],
            usage=None,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=chat_payload)),
            ),
            responses=SimpleNamespace(create=AsyncMock()),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"openai_api": "chat_completions"},
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "chat path")
        api.chat.completions.create.assert_awaited_once()
        api.responses.create.assert_not_called()

    async def test_get_completion_raises_on_invalid_surface(self) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "invalid_surface"
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock()),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

        api.chat.completions.create.assert_not_called()
        api.responses.create.assert_not_called()

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"openai_api": "bad_api"},
        )
        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(request)

    async def test_get_completion_responses_request_shaping_and_passthrough(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        completed_payload = {
            "id": "resp_2",
            "object": "response",
            "created_at": 124,
            "status": "completed",
            "service_tier": "default",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_2",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }
        stream_events = [
            {"type": "response.completed", "response": completed_payload},
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(
                create=AsyncMock(return_value=_stream_chunks(stream_events)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage(role="system", content="System one."),
                CompletionMessage(role="system", content={"policy": "strict"}),
                CompletionMessage(role="user", content="hello"),
                CompletionMessage(role="assistant", content="history"),
            ],
            inference=CompletionInferenceConfig(
                max_completion_tokens=111,
                temperature=0.7,
                top_p=0.6,
                stream=True,
                stream_options={"include_usage": True},
            ),
            vendor_params={
                "openai_api": "responses",
                "include": ["reasoning.encrypted_content"],
                "max_tool_calls": 2,
                "previous_response_id": "resp_prev",
                "prompt_cache_key": "cache-1",
                "reasoning": {"effort": "medium"},
                "safety_identifier": "safe_1",
                "text": {"format": {"type": "text"}},
                "truncation": "disabled",
                "conversation": "conv_1",
                "metadata": {"scope": "gateway"},
                "parallel_tool_calls": True,
                "service_tier": "auto",
                "store": True,
                "temperature": 0.1,
                "top_p": 0.1,
                "tool_choice": "auto",
                "tools": [{"type": "function", "name": "lookup"}],
                "top_logprobs": 2,
                "user": "u-1",
            },
        )
        response = await gateway.get_completion(request)

        _, kwargs = api.responses.create.await_args
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["stream_options"], {"include_usage": True})
        self.assertEqual(kwargs["max_output_tokens"], 111)
        self.assertNotIn("max_tokens", kwargs)
        self.assertNotIn("max_completion_tokens", kwargs)
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertEqual(kwargs["top_p"], 0.6)
        self.assertIn("System one.", kwargs["instructions"])
        self.assertIn('{"policy": "strict"}', kwargs["instructions"])
        self.assertEqual(
            kwargs["input"],
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "history"},
            ],
        )
        self.assertEqual(kwargs["include"], ["reasoning.encrypted_content"])
        self.assertEqual(kwargs["max_tool_calls"], 2)
        self.assertEqual(kwargs["conversation"], "conv_1")
        self.assertEqual(response.content, "ok")
        api.chat.completions.create.assert_not_called()

    async def test_get_completion_responses_does_not_emit_chat_only_fields(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        response_payload = {
            "id": "resp_3",
            "object": "response",
            "created_at": 125,
            "status": "completed",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_3",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
        }
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock(return_value=response_payload)),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stop=["END"]),
            vendor_params={
                "openai_api": "responses",
                "functions": [{"name": "x"}],
                "response_format": {"type": "json_object"},
            },
        )
        await gateway.get_completion(request)

        _, kwargs = api.responses.create.await_args
        self.assertNotIn("stop", kwargs)
        self.assertNotIn("functions", kwargs)
        self.assertNotIn("function_call", kwargs)
        self.assertNotIn("response_format", kwargs)
        self.assertNotIn("max_completion_tokens", kwargs)
        self.assertNotIn("max_tokens", kwargs)

    async def test_get_completion_responses_non_stream_structured_content(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        response_payload = {
            "id": "resp_4",
            "object": "response",
            "created_at": 126,
            "status": "completed",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_4",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "reasoning", "summary": [{"text": "trace"}]}],
                }
            ],
        }
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock(return_value=response_payload)),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())

        self.assertEqual(response.content[0]["type"], "reasoning")
        self.assertEqual(
            response.vendor_fields["structured_content_blocks"][0]["type"],
            "reasoning",
        )

    async def test_get_completion_responses_non_stream_tool_calls_and_usage(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        response_payload = {
            "id": "resp_5",
            "object": "response",
            "created_at": 127,
            "status": "completed",
            "service_tier": "default",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_5",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "hello"}],
                },
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "name": "lookup_weather",
                    "call_id": "call_1",
                    "arguments": "{\"city\":\"Paris\"}",
                },
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
                "output_tokens_details": {"reasoning_tokens": 2},
            },
        }
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock(return_value=response_payload)),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())

        self.assertEqual(response.tool_calls[0]["id"], "fc_1")
        self.assertEqual(response.usage.input_tokens, 10)
        self.assertEqual(response.usage.output_tokens, 4)
        self.assertEqual(
            response.usage.vendor_fields["output_tokens_details"]["reasoning_tokens"],
            2,
        )
        self.assertEqual(response.vendor_fields["id"], "resp_5")
        self.assertEqual(response.vendor_fields["status"], "completed")

    async def test_get_completion_responses_stream_aggregates_events(self) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        completed_payload = {
            "id": "resp_6",
            "object": "response",
            "created_at": 128,
            "status": "completed",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_6",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "hello"}],
                },
                {
                    "id": "fc_2",
                    "type": "function_call",
                    "name": "lookup_weather",
                    "call_id": "call_2",
                    "arguments": "",
                },
            ],
            "usage": {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9},
        }
        stream_events = [
            {"type": "response.output_text.delta", "delta": "hel"},
            {"type": "response.output_text.delta", "delta": "lo"},
            {
                "type": "response.output_item.added",
                "item": {"id": "fc_2", "type": "function_call", "name": "lookup_weather"},
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_2",
                "delta": "{\"city\":\"",
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_2",
                "arguments": "{\"city\":\"Paris\"}",
            },
            {"type": "response.completed", "response": completed_payload},
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(
                create=AsyncMock(return_value=_stream_chunks(stream_events)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
            vendor_params={"openai_api": "responses"},
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "hello")
        self.assertEqual(response.tool_calls[0]["id"], "fc_2")
        self.assertEqual(response.tool_calls[0]["arguments"], "{\"city\":\"Paris\"}")
        self.assertEqual(response.usage.total_tokens, 9)
        self.assertEqual(response.vendor_fields["stream_text_deltas"], "hello")
        self.assertEqual(response.vendor_fields["stream_output_items"][0]["id"], "fc_2")
        self.assertEqual(
            response.vendor_fields["stream_tool_call_arguments"]["fc_2"],
            "{\"city\":\"Paris\"}",
        )

    async def test_get_completion_responses_stream_raises_on_error_event(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        stream_events = [{"type": "error", "message": "boom"}]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(
                create=AsyncMock(return_value=_stream_chunks(stream_events)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
            vendor_params={"openai_api": "responses"},
        )
        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(request)

    async def test_get_completion_responses_stream_raises_without_terminal_payload(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        stream_events = [{"type": "response.output_text.delta", "delta": "hello"}]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(
                create=AsyncMock(return_value=_stream_chunks(stream_events)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
            vendor_params={"openai_api": "responses"},
        )
        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(request)

    async def test_get_completion_responses_stream_raises_when_no_events(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock(return_value=_stream_chunks([]))),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
            vendor_params={"openai_api": "responses"},
        )
        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(request)

    async def test_get_completion_responses_fail_fast_without_chat_fallback(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(
                create=AsyncMock(side_effect=OpenAIError("bad request")),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

        api.chat.completions.create.assert_not_called()

    async def test_get_completion_responses_rejects_removed_legacy_max_tokens_vendor_param(
        self,
    ) -> None:
        config = _make_config()
        config.openai.api.dict["completion"]["surface"] = "responses"
        logging_gateway = Mock()
        response_payload = {
            "id": "resp_7",
            "object": "response",
            "created_at": 129,
            "status": "completed",
            "model": "gpt-4o-mini",
            "output": [
                {
                    "id": "msg_7",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ],
        }
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            ),
            responses=SimpleNamespace(create=AsyncMock(return_value=response_payload)),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=api,
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(max_completion_tokens=64),
            vendor_params={
                "openai_api": "responses",
                "use_legacy_max_tokens": True,
            },
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Removed legacy vendor param 'use_legacy_max_tokens'",
        ):
            await gateway.get_completion(request)

    async def test_get_completion_wraps_openai_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=OpenAIError("bad request")),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

        logging_gateway.warning.assert_called_once()

    async def test_get_completion_rethrows_completion_gateway_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        sentinel = CompletionGatewayError(
            provider="openai",
            operation="completion",
            message="already wrapped",
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=sentinel)),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError) as context:
            await gateway.get_completion(_simple_request())

        self.assertIs(context.exception, sentinel)

    async def test_get_completion_raises_gateway_error_on_failure(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(side_effect=RuntimeError("boom")),
                ),
            ),
        )

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

        logging_gateway.warning.assert_called_once()

    def test_resolve_operation_config_validation(self) -> None:
        logging_gateway = Mock()

        missing_cfg = SimpleNamespace(
            openai=SimpleNamespace(api=SimpleNamespace(key="k", dict={}))
        )
        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=Mock(),
        ):
            gateway = OpenAICompletionGateway(missing_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

        invalid_cfg = SimpleNamespace(
            openai=SimpleNamespace(
                api=SimpleNamespace(key="k", dict={"completion": "x"}),
            )
        )
        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=Mock(),
        ):
            gateway = OpenAICompletionGateway(invalid_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

        model_missing = SimpleNamespace(
            openai=SimpleNamespace(
                api=SimpleNamespace(key="k", dict={"completion": {}}),
            )
        )
        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=Mock(),
        ):
            gateway = OpenAICompletionGateway(model_missing, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

    def test_usage_from_payload_returns_none_without_tokens(self) -> None:
        usage = OpenAICompletionGateway._usage_from_payload({"cached_tokens": 2})
        self.assertIsNone(usage)

    def test_normalize_helpers_cover_edge_cases(self) -> None:
        class _ModelDumpObject:
            @staticmethod
            def model_dump(exclude_none: bool = True) -> dict[str, int]:
                _ = exclude_none
                return {"value": 1}

        class _ModelDumpNonDictObject:
            @staticmethod
            def model_dump(exclude_none: bool = True) -> list[int]:
                _ = exclude_none
                return [1]

        class _PlainObject:
            def __init__(self) -> None:
                self.value = 2

        self.assertEqual(OpenAICompletionGateway._normalize_dict({"a": 1}), {"a": 1})
        self.assertEqual(OpenAICompletionGateway._normalize_dict(None), {})
        self.assertEqual(
            OpenAICompletionGateway._normalize_dict(_ModelDumpObject()),
            {"value": 1},
        )
        self.assertEqual(
            OpenAICompletionGateway._normalize_dict(_ModelDumpNonDictObject()), {}
        )
        self.assertEqual(OpenAICompletionGateway._normalize_dict(1), {})

        normalized_list = OpenAICompletionGateway._normalize_content(
            [{"a": 1}, _PlainObject(), 1],
        )
        self.assertEqual(normalized_list[1]["value"], 2)

        normalized_object = OpenAICompletionGateway._normalize_content(_PlainObject())
        self.assertEqual(normalized_object["value"], 2)
        self.assertIsNone(OpenAICompletionGateway._normalize_content(1))

        self.assertEqual(
            OpenAICompletionGateway._normalize_list_of_dicts(
                [{"a": 1}, _PlainObject(), 1]
            ),
            [{"a": 1}, {"value": 2}],
        )

    def test_responses_serializer_fallbacks_and_surface_validation(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=Mock(),
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        operation_config = {"model": "gpt-4o-mini", "surface": "responses"}
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="system", content=None)],
            vendor_params={"openai_api": "responses"},
        )
        _, kwargs = gateway._serialize_responses_kwargs(request, operation_config)
        self.assertEqual(kwargs["input"], [])
        self.assertNotIn("instructions", kwargs)
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)

        system_only_request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="system", content="policy")],
            vendor_params={"openai_api": "responses"},
        )
        _, kwargs = gateway._serialize_responses_kwargs(
            system_only_request,
            operation_config,
        )
        self.assertEqual(kwargs["instructions"], "policy")
        self.assertNotIn("input", kwargs)

        _, kwargs = gateway._serialize_responses_kwargs(
            request,
            {"model": "gpt-4o-mini", "max_output_tokens": "25"},
        )
        self.assertEqual(kwargs["max_output_tokens"], 25)
        _, kwargs = gateway._serialize_responses_kwargs(
            request,
            {"model": "gpt-4o-mini", "max_completion_tokens": "24"},
        )
        self.assertEqual(kwargs["max_output_tokens"], 24)
        _, kwargs = gateway._serialize_responses_kwargs(
            request,
            {"model": "gpt-4o-mini", "max_tokens": "23"},
        )
        self.assertNotIn("max_output_tokens", kwargs)

        invalid_surface_request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"openai_api": 1},
        )
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_openai_surface(
                invalid_surface_request,
                {"model": "gpt-4o-mini", "surface": "chat_completions"},
            )

    async def test_parse_responses_stream_additional_branches(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=Mock(),
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        stream_with_invalid_chunks = _stream_chunks(
            [
                {"type": "response.output_text.delta", "delta": 1},
                {"type": "response.output_item.added", "item": 1},
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": 1,
                    "delta": 1,
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": 1,
                    "arguments": 1,
                },
                {
                    "type": "response.function_call_arguments.done",
                    "item_id": "call_1",
                    "arguments": "{}",
                },
                {"type": "response.queued"},
                {
                    "type": "response.completed",
                    "response": {
                        "model": "gpt-4o-mini",
                        "status": "completed",
                        "output": [],
                    },
                },
            ]
        )
        parsed = await gateway._parse_responses_stream_response(
            stream=stream_with_invalid_chunks,
            model="gpt-4o-mini",
            operation="completion",
        )
        self.assertIsNone(parsed.content)

        stream_with_delta_fallback = _stream_chunks(
            [
                {"type": "response.output_text.delta", "delta": "hello"},
                {
                    "type": "response.completed",
                    "response": {
                        "model": "gpt-4o-mini",
                        "status": "completed",
                        "output": [],
                    },
                },
            ]
        )
        parsed = await gateway._parse_responses_stream_response(
            stream=stream_with_delta_fallback,
            model="gpt-4o-mini",
            operation="completion",
        )
        self.assertEqual(parsed.content, "hello")

        failed_stream = _stream_chunks(
            [
                {
                    "type": "response.failed",
                    "response": {"error": {"message": "failed"}},
                }
            ]
        )
        with self.assertRaises(CompletionGatewayError) as failed_context:
            await gateway._parse_responses_stream_response(
                stream=failed_stream,
                model="gpt-4o-mini",
                operation="completion",
            )
        self.assertEqual(str(failed_context.exception), "failed")

        incomplete_stream = _stream_chunks(
            [
                {
                    "type": "response.incomplete",
                    "response": {
                        "incomplete_details": {"reason": "max_output_tokens"}
                    },
                }
            ]
        )
        with self.assertRaises(CompletionGatewayError) as incomplete_context:
            await gateway._parse_responses_stream_response(
                stream=incomplete_stream,
                model="gpt-4o-mini",
                operation="completion",
            )
        self.assertIn("max_output_tokens", str(incomplete_context.exception))

    def test_responses_helper_branches(self) -> None:
        config = _make_config()
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI",
            return_value=Mock(),
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)

        message_payload, content, _ = gateway._extract_responses_content(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": {"type": "output_text", "text": "hi"},
                }
            ]
        )
        self.assertEqual(message_payload["role"], "assistant")
        self.assertEqual(content, "hi")

        _, content, _ = gateway._extract_responses_content([{"type": "function_call"}])
        self.assertIsNone(content)
        _, content, _ = gateway._extract_responses_content(
            [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": None,
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "a"}],
                },
            ]
        )
        self.assertEqual(content, "a")

        class _DirectOutputText:
            output_text = "direct"

        self.assertEqual(
            gateway._extract_responses_output_text(_DirectOutputText(), {}),
            "direct",
        )
        self.assertEqual(
            gateway._extract_responses_output_text(None, {"output_text": "payload"}),
            "payload",
        )
        self.assertEqual(
            gateway._extract_responses_output_text(None, {"text": {"value": "field"}}),
            "field",
        )
        self.assertIsNone(gateway._extract_responses_output_text(None, {}))

        parsed_response = gateway._parse_responses_standard_response(
            response={
                "model": "gpt-4o-mini",
                "status": "incomplete",
                "output": [],
                "output_text": "fallback text",
                "error": {"message": "x"},
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            model="gpt-4o-mini",
            operation="completion",
        )
        self.assertEqual(parsed_response.content, "fallback text")
        self.assertIn("error", parsed_response.vendor_fields)
        self.assertIn("incomplete_details", parsed_response.vendor_fields)
        self.assertEqual(parsed_response.stop_reason, "max_output_tokens")

        merged = gateway._merge_responses_tool_calls(
            parsed_tool_calls=[
                {"id": None, "type": "function_call", "arguments": ""},
                {"id": "known", "type": "function_call", "arguments": "{}"},
                {"id": "no_args", "type": "function_call", "arguments": ""},
            ],
            stream_tool_calls=[
                {"type": "function_call", "name": "no_id"},
                {"id": "new", "type": "function_call", "arguments": ""},
            ],
            stream_tool_call_arguments={
                "known": "{\"a\":1}",
                "new": "{\"b\":2}",
                "orphan": "{\"c\":3}",
            },
        )
        self.assertTrue(any(item.get("id") == "orphan" for item in merged))

        self.assertEqual(
            gateway._extract_responses_stop_reason(
                {"status": "incomplete", "incomplete_details": {"reason": "r"}}
            ),
            "r",
        )
        self.assertEqual(
            gateway._extract_responses_stop_reason(
                {"status": "incomplete", "incomplete_details": {"reason": 1}}
            ),
            "incomplete",
        )
        self.assertIsNone(gateway._extract_responses_stop_reason({}))
        self.assertFalse(gateway._is_responses_tool_call_item(1))
        self.assertEqual(
            gateway._extract_responses_terminal_error_message(
                {},
                fallback="fallback",
            ),
            "fallback",
        )

        class _EmptyPayload:
            @staticmethod
            def model_dump(exclude_none: bool = True) -> dict[str, Any]:
                _ = exclude_none
                return {}

        self.assertIsNone(gateway._usage_from_payload(_EmptyPayload()))

    def test_constructor_raises_when_timeout_missing_in_production(self) -> None:
        config = _make_config()
        config.openai.api.timeout_seconds = None
        config.mugen = SimpleNamespace(environment="production")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.completion.openai.AsyncOpenAI") as async_openai,
            self.assertRaisesRegex(
                RuntimeError,
                "OpenAICompletionGateway: Missing required production configuration field\\(s\\): timeout_seconds.",
            ),
        ):
            OpenAICompletionGateway(config, logging_gateway)

        async_openai.assert_not_called()
