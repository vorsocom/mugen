"""Unit tests for mugen.core.gateway.completion.openai.OpenAICompletionGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

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


async def _stream_chunks(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class TestMugenGatewayCompletionOpenAI(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for OpenAI completion."""

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
            [{"role": "user", "content": "hello"}],
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
            inference=CompletionInferenceConfig(
                max_completion_tokens=64,
                max_tokens=16,
            ),
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

    async def test_get_completion_uses_legacy_max_tokens_when_requested(self) -> None:
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
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="gpt-4o-mini",
            temperature=0.1,
            top_p=0.8,
            stream=False,
            max_tokens=64,
        )

    async def test_get_completion_uses_vendor_stream_overrides(self) -> None:
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
            vendor_params={"stream": True, "stream_options": {"include_usage": True}},
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
            await gateway.get_completion([{"role": "user", "content": "hello"}])

        _, kwargs = api.chat.completions.create.await_args
        self.assertEqual(kwargs["max_completion_tokens"], 21)

        del config.openai.api.dict["completion"]["max_completion_tokens"]
        config.openai.api.dict["completion"]["max_tokens"] = "17"
        api.chat.completions.create.reset_mock()

        with patch(
            "mugen.core.gateway.completion.openai.AsyncOpenAI", return_value=api
        ):
            gateway = OpenAICompletionGateway(config, logging_gateway)
            await gateway.get_completion([{"role": "user", "content": "hello"}])

        _, kwargs = api.chat.completions.create.await_args
        self.assertEqual(kwargs["max_completion_tokens"], 17)

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

        await gateway.get_completion([{"role": "user", "content": "hello"}])

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
            await gateway.get_completion([{"role": "user", "content": "hello"}])

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

        response = await gateway.get_completion([{"role": "user", "content": "hello"}])
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

        response = await gateway.get_completion([{"role": "user", "content": "hello"}])
        self.assertEqual(response.content, "hello")
        self.assertEqual(response.vendor_fields, {})

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
            await gateway.get_completion([{"role": "user", "content": "hello"}])

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
            await gateway.get_completion([{"role": "user", "content": "hello"}])

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
            await gateway.get_completion([{"role": "user", "content": "hello"}])

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
