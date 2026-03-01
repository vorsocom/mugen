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


async def _stream_chunks(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


def _simple_request() -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
    )


class TestMugenGatewayCompletionGroq(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for Groq completion."""

    async def test_check_readiness_resolves_required_operation_configs(self) -> None:
        config = _make_config()
        config.groq.api.dict["classification"] = dict(config.groq.api.dict["completion"])
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        await gateway.check_readiness()

    async def test_get_completion_builds_request_and_returns_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        usage = SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            completion_time=0.1,
        )
        response_payload = SimpleNamespace(
            id="chatcmpl-1",
            model="llama-3.1-8b-instant",
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
            _simple_request(),
        )

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertEqual(response.message["role"], "assistant")
        self.assertEqual(response.vendor_fields["id"], "chatcmpl-1")
        self.assertEqual(response.usage.vendor_fields["completion_time"], 0.1)
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
            max_completion_tokens=42,
            frequency_penalty=0.2,
            presence_penalty=0.3,
            response_format={"type": "json_object"},
            seed=123,
            tool_choice="none",
            tools=[{"type": "function"}],
            user="u-1",
        )

    async def test_get_completion_prefers_max_completion_tokens(self) -> None:
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
                max_completion_tokens=64,
                max_tokens=16,
            ),
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            top_p=0.8,
            stream=False,
            max_completion_tokens=64,
        )

    async def test_get_completion_uses_legacy_max_tokens_when_requested(self) -> None:
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
                max_completion_tokens=64,
            ),
            vendor_params={"use_legacy_max_tokens": True},
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            top_p=0.8,
            stream=False,
            max_tokens=64,
        )

    async def test_get_completion_streams_content_tool_calls_and_usage(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
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
                                )
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
                    queue_time=0.2,
                ),
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.tool_calls[0]["id"], "call_1")
        self.assertEqual(response.usage.total_tokens, 13)
        self.assertEqual(response.usage.vendor_fields["queue_time"], 0.2)
        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            top_p=0.8,
            stream=True,
        )

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
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "")
        self.assertEqual(response.usage.total_tokens, 3)

    async def test_get_completion_preserves_structured_message_content(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="llama-3.1-8b-instant",
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    message=SimpleNamespace(
                        role="assistant",
                        content=[
                            {"type": "output_text", "text": "hi"},
                            {"type": "reasoning", "text": "trace"},
                        ],
                        tool_calls=[
                            SimpleNamespace(
                                id="tool-1",
                                type="function",
                                function={"name": "lookup"},
                            )
                        ],
                    ),
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

        response = await gateway.get_completion(
            _simple_request(),
        )

        self.assertEqual(response.content[0]["type"], "output_text")
        self.assertEqual(response.stop_reason, "tool_calls")
        self.assertEqual(response.tool_calls[0]["id"], "tool-1")

    async def test_get_completion_uses_vendor_stream_overrides(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop", delta=SimpleNamespace())],
                usage=None,
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": True, "stream_options": {"include_usage": True}},
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            top_p=0.8,
            stream=True,
            stream_options={"include_usage": True},
        )

    async def test_get_completion_vendor_stream_parses_string_false(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="llama-3.1-8b-instant",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
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
            vendor_params={"stream": "false"},
        )
        await gateway.get_completion(request)

        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-3.1-8b-instant",
            temperature=0.1,
            top_p=0.8,
            stream=False,
        )

    async def test_get_completion_rejects_invalid_vendor_stream_boolean(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": "definitely"},
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Invalid boolean value for vendor_params.stream",
        ):
            await gateway.get_completion(request)

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
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content[0]["type"], "output_text")
        self.assertEqual(response.vendor_fields["stream_content_deltas"][1]["type"], "reasoning")

    async def test_get_completion_stream_preserves_structured_object_delta(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(
                            content=SimpleNamespace(type="output_text", text="hello"),
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
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content[0]["text"], "hello")

    async def test_get_completion_stream_ignores_unrecognized_delta_content(self) -> None:
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
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        response = await gateway.get_completion(request)

        self.assertEqual(response.content, "")

    async def test_get_completion_raises_when_response_has_no_choices(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            model="llama-3.1-8b-instant",
                            choices=[],
                            usage=None,
                        )
                    ),
                )
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

    async def test_get_completion_includes_additional_choices_metadata(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        payload = SimpleNamespace(
            model="llama-3.1-8b-instant",
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
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())
        self.assertEqual(response.vendor_fields["additional_choices"][0]["finish_reason"], "length")

    async def test_get_completion_handles_response_without_payload_dict(self) -> None:
        class _CompletionNoDict:
            __slots__ = ("model", "choices", "usage")

            def __init__(self) -> None:
                self.model = "llama-3.1-8b-instant"
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
            )
        )

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq", return_value=api):
            gateway = GroqCompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())
        self.assertEqual(response.content, "hello")
        self.assertEqual(response.vendor_fields, {})

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
            await gateway.get_completion(_simple_request())

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
            await gateway.get_completion(_simple_request())

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
            await gateway.get_completion(_simple_request())

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

    def test_usage_from_response_includes_vendor_fields(self) -> None:
        payload = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=2,
                completion_tokens=3,
                total_tokens=5,
                prompt_time=0.1,
                completion_time=0.2,
            )
        )

        usage = GroqCompletionGateway._usage_from_response(payload)

        self.assertEqual(usage.input_tokens, 2)
        self.assertEqual(usage.output_tokens, 3)
        self.assertEqual(usage.total_tokens, 5)
        self.assertEqual(usage.vendor_fields["prompt_time"], 0.1)
        self.assertEqual(usage.vendor_fields["completion_time"], 0.2)

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

        self.assertEqual(GroqCompletionGateway._normalize_dict({"a": 1}), {"a": 1})
        self.assertEqual(GroqCompletionGateway._normalize_dict(None), {})
        self.assertEqual(
            GroqCompletionGateway._normalize_dict(_ModelDumpObject()),
            {"value": 1},
        )
        self.assertEqual(GroqCompletionGateway._normalize_dict(_ModelDumpNonDictObject()), {})
        self.assertEqual(GroqCompletionGateway._normalize_dict(1), {})

        normalized_list = GroqCompletionGateway._normalize_content(
            [{"a": 1}, _PlainObject(), 1],
        )
        self.assertEqual(normalized_list[1]["value"], 2)

        normalized_object = GroqCompletionGateway._normalize_content(_PlainObject())
        self.assertEqual(normalized_object["value"], 2)
        self.assertIsNone(GroqCompletionGateway._normalize_content(1))

        self.assertEqual(
            GroqCompletionGateway._normalize_list_of_dicts([{"a": 1}, 1]),
            [{"a": 1}],
        )

    def test_constructor_applies_timeout_when_configured(self) -> None:
        config = _make_config()
        config.groq.api.timeout_seconds = 9

        with patch("mugen.core.gateway.completion.groqq.AsyncGroq") as async_groq:
            GroqCompletionGateway(config, Mock())

        async_groq.assert_called_once_with(api_key="gsk_test", timeout=9.0)

    def test_timeout_resolution_logs_invalid_values(self) -> None:
        gateway = GroqCompletionGateway.__new__(GroqCompletionGateway)
        gateway._config = _make_config()  # pylint: disable=protected-access
        gateway._logging_gateway = Mock()  # pylint: disable=protected-access

        self.assertIsNone(gateway._resolve_timeout_seconds())
        gateway._config.groq.api.timeout_seconds = "bad"  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_timeout_seconds())
        gateway._config.groq.api.timeout_seconds = 0  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_timeout_seconds())
        self.assertGreaterEqual(gateway._logging_gateway.warning.call_count, 2)  # pylint: disable=protected-access

    def test_constructor_raises_when_timeout_missing_in_production(self) -> None:
        config = _make_config()
        config.mugen = SimpleNamespace(environment="production")
        logging_gateway = Mock()
        with (
            patch("mugen.core.gateway.completion.groqq.AsyncGroq") as async_groq,
            self.assertRaisesRegex(
                RuntimeError,
                "GroqCompletionGateway: Missing required production configuration field\\(s\\): timeout_seconds.",
            ),
        ):
            GroqCompletionGateway(config, logging_gateway)
        async_groq.assert_not_called()
