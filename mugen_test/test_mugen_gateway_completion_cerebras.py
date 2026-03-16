"""Unit tests for mugen.core.gateway.completion.cerebras.CerebrasCompletionGateway."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from cerebras.cloud.sdk import APIError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.cerebras import CerebrasCompletionGateway


def _make_config(
    *,
    key: object = "csk-test",
    base_url: object = "",
    timeout_seconds: object = "12.5",
) -> SimpleNamespace:
    operation_cfg = {
        "model": "llama-4-scout-17b-16e-instruct",
        "temp": 0.1,
        "top_p": 0.8,
        "max_completion_tokens": 128,
    }
    return SimpleNamespace(
        mugen=SimpleNamespace(environment="development"),
        cerebras=SimpleNamespace(
            api=SimpleNamespace(
                key=key,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                dict={
                    "classification": dict(operation_cfg),
                    "completion": dict(operation_cfg),
                },
            )
        ),
    )


def _simple_request() -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
    )


async def _stream_chunks(chunks: list[SimpleNamespace]):
    for chunk in chunks:
        yield chunk


class TestMugenGatewayCompletionCerebras(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for Cerebras completion."""

    def test_constructor_uses_default_base_url_and_timeout(self) -> None:
        config = _make_config(base_url="", timeout_seconds="3.5")
        logging_gateway = Mock()

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras") as async_cerebras:
            CerebrasCompletionGateway(config, logging_gateway)

        async_cerebras.assert_called_once_with(
            api_key="csk-test",
            base_url="https://api.cerebras.ai/v1",
            timeout=3.5,
        )

    def test_constructor_uses_explicit_base_url_and_omits_timeout(self) -> None:
        config = _make_config(
            base_url="https://custom.cerebras.local/v1",
            timeout_seconds=None,
        )
        logging_gateway = Mock()

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras") as async_cerebras:
            CerebrasCompletionGateway(config, logging_gateway)

        async_cerebras.assert_called_once_with(
            api_key="csk-test",
            base_url="https://custom.cerebras.local/v1",
        )

    def test_constructor_requires_cerebras_api_section(self) -> None:
        config = SimpleNamespace(
            mugen=SimpleNamespace(environment="development"),
            cerebras=SimpleNamespace(),
        )
        logging_gateway = Mock()

        with self.assertRaisesRegex(RuntimeError, "cerebras.api section is required"):
            CerebrasCompletionGateway(config, logging_gateway)

    def test_constructor_requires_key(self) -> None:
        config = _make_config(key="   ")
        logging_gateway = Mock()

        with self.assertRaisesRegex(RuntimeError, "cerebras.api.key is required"):
            CerebrasCompletionGateway(config, logging_gateway)

    def test_constructor_rejects_invalid_timeout(self) -> None:
        config = _make_config(timeout_seconds="bad")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.completion.cerebras.AsyncCerebras") as async_cerebras,
            self.assertRaisesRegex(RuntimeError, "timeout_seconds"),
        ):
            CerebrasCompletionGateway(config, logging_gateway)

        async_cerebras.assert_not_called()

    def test_constructor_requires_timeout_in_production(self) -> None:
        config = _make_config(timeout_seconds=None)
        config.mugen.environment = "production"

        with self.assertRaisesRegex(
            RuntimeError,
            "Missing required production configuration field\\(s\\): timeout_seconds.",
        ):
            CerebrasCompletionGateway(config, Mock())

    async def test_check_readiness_resolves_required_operation_configs(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        await gateway.check_readiness()
        api.models.list.assert_awaited_once_with(limit=1)

    async def test_check_readiness_raises_when_models_list_is_missing(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            models=SimpleNamespace(list=None),
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(RuntimeError, "readiness probe unavailable"):
            await gateway.check_readiness()

    async def test_check_readiness_falls_back_when_limit_is_unsupported(self) -> None:
        config = _make_config()
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
            models=SimpleNamespace(list=_list_models),
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        await gateway.check_readiness()
        self.assertEqual(calls, [{"limit": 1}, {}])

    async def test_check_readiness_uses_default_timeout_when_missing(self) -> None:
        config = _make_config(timeout_seconds=None)
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )
        wait_for_calls: list[float] = []

        async def _wait_for(awaitable, timeout):
            wait_for_calls.append(float(timeout))
            return await awaitable

        with (
            patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api),
            patch("mugen.core.gateway.completion.cerebras.asyncio.wait_for", side_effect=_wait_for),
        ):
            gateway = CerebrasCompletionGateway(config, logging_gateway)
            await gateway.check_readiness()

        self.assertEqual(wait_for_calls, [5.0])

    async def test_check_readiness_wraps_probe_failures(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        async def _wait_for(awaitable, timeout):
            _ = timeout
            await awaitable
            raise RuntimeError("probe down")

        with (
            patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api),
            patch("mugen.core.gateway.completion.cerebras.asyncio.wait_for", side_effect=_wait_for),
        ):
            gateway = CerebrasCompletionGateway(config, logging_gateway)
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_aclose_handles_missing_sync_and_async_close(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        gateway._api = SimpleNamespace()  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        calls: list[str] = []

        def _sync_close():
            calls.append("sync")
            return None

        async def _async_close():
            calls.append("async")
            return None

        gateway._api = SimpleNamespace(close=_sync_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        gateway._api = SimpleNamespace(close=_async_close)  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())
        self.assertEqual(calls, ["sync", "async"])

    async def test_get_completion_builds_request_and_returns_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            id="chatcmpl-1",
            object="chat.completion",
            created=123,
            system_fingerprint="fp_1",
            service_tier="default",
            time_info={"queue_time": 0.1},
            model="llama-4-scout-17b-16e-instruct",
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
            usage=SimpleNamespace(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
                completion_tokens_details={"accepted_prediction_tokens": 1},
            ),
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=response_payload),
                )
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertEqual(
            response.usage.vendor_fields["completion_tokens_details"][
                "accepted_prediction_tokens"
            ],
            1,
        )
        self.assertEqual(response.message["role"], "assistant")
        self.assertEqual(response.vendor_fields["id"], "chatcmpl-1")
        self.assertEqual(response.vendor_fields["time_info"]["queue_time"], 0.1)
        api.chat.completions.create.assert_awaited_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="llama-4-scout-17b-16e-instruct",
            temperature=0.1,
            top_p=0.8,
            max_completion_tokens=128,
            stream=False,
        )

    async def test_get_completion_serializes_structured_message_content(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="llama-4-scout-17b-16e-instruct",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(
                        role="assistant",
                        content="ok",
                        tool_calls=[],
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

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage(role="system", content={"policy": "strict"}),
                CompletionMessage(
                    role="user",
                    content={"message": "hello", "attachment_context": [{"kind": "image"}]},
                ),
            ],
        )
        await gateway.get_completion(request)

        _, kwargs = api.chat.completions.create.await_args
        self.assertEqual(
            kwargs["messages"],
            [
                {"role": "system", "content": '{"policy": "strict"}'},
                {
                    "role": "user",
                    "content": (
                        '{"message": "hello", "attachment_context": [{"kind": "image"}]}'
                    ),
                },
            ],
        )

    async def test_get_completion_uses_explicit_inference_and_vendor_subset(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            model="llama-4-scout-17b-16e-instruct",
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(role="assistant", content="ok", tool_calls=[]),
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

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                temperature=0.7,
                top_p=0.6,
                max_completion_tokens=42,
                stop=["DONE"],
            ),
            vendor_params={
                "clear_thinking": True,
                "reasoning_effort": "low",
                "frequency_penalty": 0.3,
            },
        )
        _ = await gateway.get_completion(request)
        kwargs = api.chat.completions.create.await_args.kwargs
        self.assertTrue(kwargs["clear_thinking"])
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertNotIn("frequency_penalty", kwargs)
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertEqual(kwargs["top_p"], 0.6)
        self.assertEqual(kwargs["max_completion_tokens"], 42)
        self.assertEqual(kwargs["stop"], ["DONE"])

    async def test_get_completion_parses_stream_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(
                            role="assistant",
                            content="hello ",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    index=0,
                                    type="function",
                                    function=SimpleNamespace(
                                        name="math",
                                        arguments="{\"a\":",
                                    ),
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
                        delta=SimpleNamespace(
                            content="world",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    index=0,
                                    type="function",
                                    function=SimpleNamespace(
                                        arguments="1}",
                                    ),
                                )
                            ],
                        ),
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=1,
                    completion_tokens=2,
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
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(request)
        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.total_tokens, 3)
        self.assertEqual(response.tool_calls[0]["id"], "call_1")
        self.assertEqual(response.tool_calls[0]["function"]["name"], "math")
        self.assertEqual(response.tool_calls[0]["function"]["arguments"], "{\"a\":1}")
        self.assertEqual(response.message["role"], "assistant")
        self.assertEqual(len(response.raw), 2)

    async def test_get_completion_stream_raises_on_error_chunk(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        chunks = [
            SimpleNamespace(
                error=SimpleNamespace(code="bad_request", message="invalid request"),
                status_code=400,
            ),
        ]
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=_stream_chunks(chunks)),
                )
            )
        )
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(CompletionGatewayError, "bad_request"):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_invalid_surface(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"cerebras_api": "responses"},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "Expected 'chat_completions'"):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_openai_api_alias(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"openai_api": "chat_completions"},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "openai_api"):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_removed_legacy_vendor_params(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": True},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "Removed legacy vendor param"):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_non_empty_stream_options(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                stream=False,
                stream_options={"include_usage": True},
            ),
        )
        with self.assertRaisesRegex(CompletionGatewayError, "stream_options is not supported"):
            await gateway.get_completion(request)

    async def test_get_completion_wraps_api_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api_error = APIError(
            "rate limited",
            httpx.Request("POST", "https://api.cerebras.ai/v1/chat/completions"),
            body={"error": {"message": "rate limited"}},
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=api_error)),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(CompletionGatewayError, "rate limited"):
            await gateway.get_completion(_simple_request())

    async def test_get_completion_wraps_unexpected_failure(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom"))),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(CompletionGatewayError, "Unexpected Cerebras completion failure"):
            await gateway.get_completion(_simple_request())

    async def test_get_completion_rethrows_completion_gateway_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=SimpleNamespace()),
                ),
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        wrapped = CompletionGatewayError(
            provider="cerebras",
            operation="completion",
            message="already wrapped",
        )
        with patch.object(
            CerebrasCompletionGateway,
            "_parse_standard_response",
            side_effect=wrapped,
        ):
            with self.assertRaisesRegex(CompletionGatewayError, "already wrapped"):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_raises_when_response_contains_error_payload(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        response_payload = SimpleNamespace(
            error=SimpleNamespace(code="bad_request", message="invalid message shape"),
            status_code=400,
        )
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=response_payload),
                )
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(CompletionGatewayError, "bad_request"):
            await gateway.get_completion(_simple_request())

    async def test_check_readiness_rejects_legacy_max_tokens_config(self) -> None:
        config = _make_config()
        config.cerebras.api.dict["classification"]["max_tokens"] = 10
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())),
            models=SimpleNamespace(list=AsyncMock(return_value=SimpleNamespace(data=[]))),
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(CompletionGatewayError, "removed legacy key 'max_tokens'"):
            await gateway.check_readiness()

    def test_constructor_defaults_base_url_when_non_string(self) -> None:
        config = _make_config(base_url=None, timeout_seconds=None)
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras") as async_cerebras:
            CerebrasCompletionGateway(config, Mock())
        async_cerebras.assert_called_once_with(
            api_key="csk-test",
            base_url="https://api.cerebras.ai/v1",
        )

    async def test_get_completion_omits_optional_fields_when_unconfigured(self) -> None:
        config = _make_config()
        config.cerebras.api.dict["completion"] = {"model": "llama-4-scout-17b-16e-instruct"}
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(
                        return_value=SimpleNamespace(
                            model="llama-4-scout-17b-16e-instruct",
                            choices=[
                                SimpleNamespace(
                                    finish_reason="stop",
                                    message=SimpleNamespace(role="assistant", content="ok", tool_calls=[]),
                                )
                            ],
                            usage=None,
                        )
                    ),
                )
            )
        )

        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                stream=False,
                stop=[],
                stream_options={},
            ),
        )
        _ = await gateway.get_completion(request)
        kwargs = api.chat.completions.create.await_args.kwargs
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)
        self.assertNotIn("stop", kwargs)
        self.assertNotIn("max_completion_tokens", kwargs)

    async def test_parse_stream_response_handles_empty_choices_and_no_message(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        api = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock()),
            )
        )
        chunks = [
            SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)),
        ]
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, logging_gateway)

        response = await gateway._parse_stream_response(  # pylint: disable=protected-access
            stream=_stream_chunks(chunks),
            model="m1",
            operation="completion",
        )
        self.assertEqual(response.content, "")
        self.assertIsNone(response.message)
        self.assertEqual(response.usage.total_tokens, 2)
        self.assertEqual(response.vendor_fields, {})

    async def test_parse_stream_response_captures_reasoning_delta(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        chunks = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(reasoning="thinking"),
                    )
                ],
                usage=None,
            )
        ]
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        response = await gateway._parse_stream_response(  # pylint: disable=protected-access
            stream=_stream_chunks(chunks),
            model="m1",
            operation="completion",
        )
        self.assertEqual(response.vendor_fields["stream_reasoning_deltas"], ["thinking"])

    async def test_parse_stream_response_handles_missing_delta_and_no_tool_calls(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(finish_reason=None, delta=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop", delta=SimpleNamespace(content="ok"))],
                usage=None,
            ),
        ]
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        response = await gateway._parse_stream_response(  # pylint: disable=protected-access
            stream=_stream_chunks(chunks),
            model="m1",
            operation="completion",
        )
        self.assertEqual(response.content, "ok")
        self.assertEqual(response.tool_calls, [])

    async def test_parse_standard_response_handles_optional_fields(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        response_payload = SimpleNamespace(
            model="m1",
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(role="assistant", content=None, reasoning="r1", tool_calls=[]),
                ),
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(role="assistant", content="alt", tool_calls=[]),
                ),
            ],
            usage=None,
        )
        response = gateway._parse_standard_response(  # pylint: disable=protected-access
            chat_completion=response_payload,
            model="m1",
            operation="completion",
        )
        self.assertEqual(response.content, "")
        self.assertEqual(response.vendor_fields["reasoning"], "r1")
        self.assertEqual(len(response.vendor_fields["additional_choices"]), 1)

    async def test_parse_standard_response_raises_when_choices_missing(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        with self.assertRaisesRegex(CompletionGatewayError, "did not include any completion choices"):
            gateway._parse_standard_response(  # pylint: disable=protected-access
                chat_completion=SimpleNamespace(model="m1", choices=[]),
                model="m1",
                operation="completion",
            )

    def test_resolve_choice_list_from_payload_or_empty(self) -> None:
        self.assertEqual(
            CerebrasCompletionGateway._resolve_choice_list(SimpleNamespace(), {"choices": [1]}),  # pylint: disable=protected-access
            [1],
        )
        self.assertEqual(
            CerebrasCompletionGateway._resolve_choice_list(SimpleNamespace(), {}),  # pylint: disable=protected-access
            [],
        )

    def test_extract_chunk_error_variants(self) -> None:
        self.assertEqual(
            CerebrasCompletionGateway._extract_chunk_error({"error": {"message": "m"}}),  # pylint: disable=protected-access
            "m",
        )
        self.assertEqual(
            CerebrasCompletionGateway._extract_chunk_error({"error": {"code": "c"}}),  # pylint: disable=protected-access
            "c",
        )
        self.assertEqual(
            CerebrasCompletionGateway._extract_chunk_error({"error": {"foo": "bar"}}),  # pylint: disable=protected-access
            "Cerebras request failed.",
        )
        self.assertEqual(
            CerebrasCompletionGateway._extract_chunk_error({"error": {}}),  # pylint: disable=protected-access
            "Cerebras request failed.",
        )
        self.assertEqual(
            CerebrasCompletionGateway._extract_chunk_error({"error": "bad"}),  # pylint: disable=protected-access
            "bad",
        )

    def test_merge_stream_tool_call_branches(self) -> None:
        tool_calls: dict[str, dict[str, object]] = {}
        CerebrasCompletionGateway._merge_stream_tool_call(tool_calls, None)  # pylint: disable=protected-access
        self.assertEqual(tool_calls, {})

        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"type": "function", "function": {"arguments": "x", "extra": 1}},
        )
        self.assertEqual(tool_calls["position:0"]["function"]["arguments"], "x")
        self.assertEqual(tool_calls["position:0"]["function"]["extra"], 1)

        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"index": 2, "type": "function", "function": {"name": "calc", "arguments": "1"}},
        )
        self.assertEqual(tool_calls["index:2"]["function"]["name"], "calc")

        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"id": "call_1", "type": "function", "function": {"arguments": "a"}},
        )
        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"id": "call_1", "type": "function", "function": {"arguments": "b"}},
        )
        self.assertEqual(tool_calls["id:call_1"]["function"]["arguments"], "ab")

        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"id": "call_2", "type": 1},
        )
        self.assertNotIn("type", tool_calls["id:call_2"])

        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"id": "call_3"},
        )
        self.assertEqual(tool_calls["id:call_3"]["id"], "call_3")

        CerebrasCompletionGateway._merge_stream_tool_call(  # pylint: disable=protected-access
            tool_calls,
            {"id": "call_4", "type": "function", "function": {"arguments": 1}},
        )
        self.assertNotIn("arguments", tool_calls["id:call_4"]["function"])

    async def test_resolve_operation_config_error_branches(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        with self.assertRaisesRegex(CompletionGatewayError, "Missing Cerebras operation configuration"):
            gateway._resolve_operation_config("missing")  # pylint: disable=protected-access

        config.cerebras.api.dict["completion"] = "bad"
        with self.assertRaisesRegex(CompletionGatewayError, "Invalid Cerebras operation configuration"):
            gateway._resolve_operation_config("completion")  # pylint: disable=protected-access

        config.cerebras.api.dict["completion"] = {}
        with self.assertRaisesRegex(CompletionGatewayError, "is missing model"):
            gateway._resolve_operation_config("completion")  # pylint: disable=protected-access

    async def test_validate_surface_aliases_rejects_non_string_surface(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"cerebras_api": 1},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "Expected 'chat_completions'"):
            gateway._validate_surface_aliases(request, {"surface": "chat_completions"})  # pylint: disable=protected-access

    async def test_parse_bool_like_rejects_invalid_value(self) -> None:
        config = _make_config()
        api = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        with patch("mugen.core.gateway.completion.cerebras.AsyncCerebras", return_value=api):
            gateway = CerebrasCompletionGateway(config, Mock())

        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream="maybe"),  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(CompletionGatewayError, "Invalid boolean value"):
            gateway._resolve_stream(request)  # pylint: disable=protected-access

    def test_usage_from_payload_and_normalizers(self) -> None:
        self.assertIsNone(CerebrasCompletionGateway._usage_from_payload(None))  # pylint: disable=protected-access
        usage = CerebrasCompletionGateway._usage_from_payload(  # pylint: disable=protected-access
            {
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "total_tokens": 3,
                "detail": "x",
            }
        )
        self.assertEqual(usage.vendor_fields["detail"], "x")

        class _WithModelDump:  # pylint: disable=too-few-public-methods
            def model_dump(self, exclude_none=True):
                _ = exclude_none
                return {"a": 1}

        class _WithToDict:  # pylint: disable=too-few-public-methods
            def to_dict(self):
                return {"b": 2}

        class _WithBadModelDump:  # pylint: disable=too-few-public-methods
            def model_dump(self, exclude_none=True):
                _ = exclude_none
                return "bad"

        class _WithBadToDict:  # pylint: disable=too-few-public-methods
            def to_dict(self):
                return "bad"

        self.assertEqual(
            CerebrasCompletionGateway._normalize_dict(_WithModelDump()),  # pylint: disable=protected-access
            {"a": 1},
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_dict(_WithToDict()),  # pylint: disable=protected-access
            {"b": 2},
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_dict(_WithBadModelDump()),  # pylint: disable=protected-access
            {},
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_dict(_WithBadToDict()),  # pylint: disable=protected-access
            {},
        )

        self.assertEqual(
            CerebrasCompletionGateway._normalize_content([{"k": 1}, _WithToDict()]),  # pylint: disable=protected-access
            [{"k": 1}, {"b": 2}],
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_content([object()]),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_content(_WithToDict()),  # pylint: disable=protected-access
            {"b": 2},
        )
        self.assertIsNone(
            CerebrasCompletionGateway._normalize_content(object())  # pylint: disable=protected-access
        )

        self.assertEqual(
            CerebrasCompletionGateway._normalize_list_of_dicts("nope"),  # pylint: disable=protected-access
            [],
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_list_of_dicts([_WithToDict()]),  # pylint: disable=protected-access
            [{"b": 2}],
        )
        self.assertEqual(
            CerebrasCompletionGateway._normalize_list_of_dicts([object()]),  # pylint: disable=protected-access
            [],
        )
