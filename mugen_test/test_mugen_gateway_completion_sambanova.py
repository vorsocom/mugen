"""Unit tests for mugen.core.gateway.completion.sambanova.SambaNovaCompletionGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.sambanova import SambaNovaCompletionGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        sambanova=SimpleNamespace(
            api=SimpleNamespace(
                key="basic_key",
                endpoint="https://example.invalid/v1/chat/completions",
                dict={
                    "completion": {
                        "model": "Meta-Llama-3.1-70B-Instruct",
                        "temp": 0.1,
                    },
                },
            )
        )
    )


def _simple_request() -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
    )


class TestMugenGatewayCompletionSambaNova(unittest.IsolatedAsyncioTestCase):
    """Covers response parsing and failure handling for SambaNova completion."""

    async def test_check_readiness_resolves_required_operation_configs(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(400, '{"error":{"message":"validation error"}}'),
        ):
            await gateway.check_readiness()

    async def test_check_readiness_returns_on_success_status(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, '{"ok": true}'),
        ):
            await gateway.check_readiness()

    async def test_check_readiness_raises_when_probe_model_missing(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["completion"]["model"] = ""
        config.sambanova.api.dict["classification"] = {"model": ""}
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with self.assertRaisesRegex(RuntimeError, "probe model is missing"):
            await gateway.check_readiness()

    async def test_check_readiness_fails_on_auth_errors(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(401, '{"error":{"message":"Unauthorized"}}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "authentication error"):
                await gateway.check_readiness()

    async def test_check_readiness_wraps_transport_failures(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            side_effect=RuntimeError("transport down"),
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_check_readiness_fails_on_provider_unavailable_status(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(503, '{"error":{"message":"unavailable"}}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                await gateway.check_readiness()

    async def test_check_readiness_fails_on_unexpected_status(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(418, '{"error":{"message":"teapot"}}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_check_readiness_uses_configured_positive_timeout(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["classification"] = dict(
            config.sambanova.api.dict["completion"]
        )
        config.sambanova.api.read_timeout_seconds = 4.0
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with (
            patch.object(
                SambaNovaCompletionGateway,
                "_perform_request",
                return_value=(400, '{"error":{"message":"validation error"}}'),
            ),
            patch("mugen.core.gateway.completion.sambanova.asyncio.wait_for", side_effect=_wait_for),
        ):
            await gateway.check_readiness()

        self.assertEqual(timeout_values, [4.0])

    async def test_aclose_is_noop(self) -> None:
        gateway = SambaNovaCompletionGateway(_make_config(), Mock())
        self.assertIsNone(await gateway.aclose())

    async def test_get_completion_parses_non_stream_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = (
            '{"choices":[{"message":{"content":"  hello world  "},'
            '"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":11,"completion_tokens":7,"total_tokens":18}}'
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            response = await gateway.get_completion(
                _simple_request(),
            )

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertEqual(response.usage.vendor_fields, {})

    async def test_get_completion_parses_stream_response(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        stream_payload = (
            'data: {"choices":[{"delta":{"content":"hello "},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        request = CompletionRequest(
            messages=[CompletionMessage(role="user", content="hello")],
            operation="completion",
            inference=CompletionInferenceConfig(stream=True),
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, stream_payload),
        ):
            response = await gateway.get_completion(request)

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.tool_calls, [])

    async def test_get_completion_raises_gateway_error_on_http_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(401, '{"error":{"message":"Unauthorized"}}'),
        ):
            with self.assertRaises(CompletionGatewayError):
                await gateway.get_completion(_simple_request())

        logging_gateway.warning.assert_called_once()

    async def test_get_completion_includes_optional_fields(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                max_completion_tokens=42,
                temperature=0.8,
                top_p=0.3,
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

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(request)

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(body["top_p"], 0.3)
        self.assertEqual(body["max_completion_tokens"], 42)
        self.assertEqual(body["frequency_penalty"], 0.2)
        self.assertEqual(body["presence_penalty"], 0.3)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["seed"], 123)
        self.assertEqual(body["tool_choice"], "none")
        self.assertEqual(body["tools"], [{"type": "function"}])
        self.assertEqual(body["user"], "u-1")

    async def test_get_completion_defaults_to_bearer_auth_header(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(_simple_request())

        _, kwargs = perform_request.call_args
        headers = kwargs["headers"]
        self.assertIn("Authorization: Bearer basic_key", headers)

    async def test_get_completion_rejects_removed_legacy_auth_vendor_param(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"sambanova_auth_scheme": "basic"},
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "Removed legacy vendor param 'sambanova_auth_scheme'",
            ):
                await gateway.get_completion(request)

    async def test_get_completion_uses_max_completion_tokens(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(max_completion_tokens=64),
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(request)

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(body["max_completion_tokens"], 64)

    async def test_get_completion_serializes_structured_message_content(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage(role="system", content={"policy": "strict"}),
                CompletionMessage(
                    role="user",
                    content={"message": "hello", "message_context": [{"role": "user"}]},
                ),
            ],
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(request)

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(
            body["messages"],
            [
                {"role": "system", "content": '{"policy": "strict"}'},
                {
                    "role": "user",
                    "content": (
                        '{"message": "hello", "message_context": [{"role": "user"}]}'
                    ),
                },
            ],
        )

    async def test_get_completion_rejects_removed_legacy_token_limit_vendor_params(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(max_completion_tokens=50),
            vendor_params={
                "sambanova_token_limit_field": "max_completion_tokens",
                "sambanova_emit_legacy_max_tokens": True,
            },
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "Removed legacy vendor param 'sambanova_token_limit_field'",
            ):
                await gateway.get_completion(request)

    async def test_get_completion_uses_contract_stream_controls(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        stream_payload = (
            'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(
                stream=True,
                stream_options={"include_usage": True, "trace": "x"},
            ),
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, stream_payload),
        ) as perform_request:
            await gateway.get_completion(request)

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertTrue(body["stream"])
        self.assertEqual(body["stream_options"], {"include_usage": True, "trace": "x"})

    async def test_get_completion_omits_stop_by_default(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(request)

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertNotIn("stop", body)

    async def test_get_completion_forwards_additional_documented_params(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={
                "top_k": 50,
                "do_sample": True,
                "reasoning_effort": "medium",
                "chat_template_kwargs": {"tokenize": False},
                "parallel_tool_calls": False,
            },
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(request)

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(body["top_k"], 50)
        self.assertTrue(body["do_sample"])
        self.assertEqual(body["reasoning_effort"], "medium")
        self.assertEqual(body["chat_template_kwargs"], {"tokenize": False})
        self.assertFalse(body["parallel_tool_calls"])

    async def test_get_completion_uses_operation_token_defaults(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["completion"]["max_completion_tokens"] = "21"
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(_simple_request())

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(body["max_completion_tokens"], 21)

        del config.sambanova.api.dict["completion"]["max_completion_tokens"]
        config.sambanova.api.dict["completion"]["max_tokens"] = "17"

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "includes removed legacy key 'max_tokens'",
            ):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_uses_operation_stop_default(self) -> None:
        config = _make_config()
        config.sambanova.api.dict["completion"]["stop"] = "###"
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(_simple_request())

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(body["stop"], ["###"])

        config.sambanova.api.dict["completion"]["stop"] = ["A", 1, "B", ""]

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ) as perform_request:
            await gateway.get_completion(_simple_request())

        _, kwargs = perform_request.call_args
        body = kwargs["body"]
        self.assertEqual(body["stop"], ["A", "B"])

    async def test_get_completion_preserves_structured_message_and_tool_calls(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = (
            '{"choices":[{"message":{"content":[{"type":"output_text","text":"hello"}],'
            '"tool_calls":[{"id":"call_1","type":"function"}]},'
            '"finish_reason":"tool_calls"}],'
            '"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2,"queue_time":0.1}}'
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            response = await gateway.get_completion(
                _simple_request(),
            )

        self.assertEqual(response.content[0]["type"], "output_text")
        self.assertEqual(response.tool_calls[0]["id"], "call_1")
        self.assertEqual(response.message["tool_calls"][0]["id"], "call_1")
        self.assertEqual(response.usage.vendor_fields["queue_time"], 0.1)

    async def test_get_completion_handles_null_non_stream_content(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":null},"finish_reason":"stop"}]}'

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            response = await gateway.get_completion(
                _simple_request(),
            )

        self.assertEqual(response.content, "")

    async def test_get_completion_stream_preserves_structured_deltas_and_tool_calls(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        stream_payload = (
            'data: {"choices":[{"delta":{"content":[{"type":"output_text","text":"hello"}],'
            '"tool_calls":[{"id":"call_1","type":"function"}]},'
            '"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, stream_payload),
        ):
            response = await gateway.get_completion(request)

        self.assertEqual(response.content[0]["text"], "hello")
        self.assertEqual(response.tool_calls[0]["id"], "call_1")
        self.assertEqual(
            response.vendor_fields["stream_content_deltas"][0]["type"],
            "output_text",
        )

    async def test_get_completion_stream_preserves_structured_object_delta(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        stream_payload = (
            'data: {"choices":[{"delta":{"content":{"type":"output_text","text":"hello"},'
            '"tool_calls":[1,{"id":"call_1","type":"function"}]},'
            '"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, stream_payload),
        ):
            response = await gateway.get_completion(request)

        self.assertEqual(response.content[0]["type"], "output_text")
        self.assertEqual(response.tool_calls[0]["id"], "call_1")

    async def test_get_completion_stream_handles_missing_delta_content(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        stream_payload = (
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, stream_payload),
        ):
            response = await gateway.get_completion(request)

        self.assertEqual(response.content, "")
        self.assertEqual(response.stop_reason, "stop")

    async def test_get_completion_wraps_request_execution_failure(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            side_effect=RuntimeError("network down"),
        ):
            with self.assertRaises(CompletionGatewayError):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_raises_gateway_error_on_invalid_payload(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, "not-json"),
        ):
            with self.assertRaises(CompletionGatewayError):
                await gateway.get_completion(_simple_request())

    def test_resolve_operation_config_validation(self) -> None:
        logging_gateway = Mock()

        missing_cfg = SimpleNamespace(
            sambanova=SimpleNamespace(api=SimpleNamespace(dict={}))
        )
        gateway = SambaNovaCompletionGateway(missing_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

        invalid_cfg = SimpleNamespace(
            sambanova=SimpleNamespace(
                api=SimpleNamespace(
                    key="k",
                    endpoint="https://example.invalid",
                    dict={"completion": "x"},
                )
            )
        )
        gateway = SambaNovaCompletionGateway(invalid_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

        model_missing_cfg = SimpleNamespace(
            sambanova=SimpleNamespace(
                api=SimpleNamespace(
                    key="k",
                    endpoint="https://example.invalid",
                    dict={"completion": {}},
                )
            )
        )
        gateway = SambaNovaCompletionGateway(model_missing_cfg, logging_gateway)
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("completion")

    def test_extract_http_error_variants(self) -> None:
        self.assertIn(
            "raw error",
            SambaNovaCompletionGateway._extract_http_error("raw error"),
        )

        self.assertEqual(
            SambaNovaCompletionGateway._extract_http_error(
                '{"error":{"message":"bad request"}}'
            ),
            "bad request",
        )

        self.assertEqual(
            SambaNovaCompletionGateway._extract_http_error('{"status":"failed"}'),
            "{'status': 'failed'}",
        )

        self.assertEqual(
            SambaNovaCompletionGateway._extract_http_error('["x","y"]'),
            "['x', 'y']",
        )

    def test_parse_streaming_response_tracks_usage_and_raises_error(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())

        response = gateway._parse_streaming_response(
            model="Meta-Llama-3.1-70B-Instruct",
            operation="completion",
            payload=(
                'data: {"choices":[{"delta":{"content":"hello "},"finish_reason":null}]}\n\n'
                'data: {"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\n'
                'data: {"choices":[{"delta":{"content":"world"},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )
        self.assertEqual(response.content, "hello world")
        self.assertIsNotNone(response.usage)
        if response.usage is not None:
            self.assertEqual(response.usage.total_tokens, 4)

        with self.assertRaises(CompletionGatewayError):
            gateway._parse_streaming_response(
                model="Meta-Llama-3.1-70B-Instruct",
                operation="completion",
                payload='data: {"error":{"message":"stream failed"}}\n\n',
            )

    def test_parse_streaming_response_rejects_non_sse_chunks(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "unsupported field"):
            gateway._parse_streaming_response(
                model="Meta-Llama-3.1-70B-Instruct",
                operation="completion",
                payload='{"choices":[{"delta":{"content":123},"finish_reason":"stop"}]}\n\n',
            )

    def test_parse_streaming_response_handles_multiline_data_and_comments(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        response = gateway._parse_streaming_response(
            model="Meta-Llama-3.1-70B-Instruct",
            operation="completion",
            payload=(
                ": keepalive\n"
                "data: {\"choices\":[{\"delta\":{\"content\":\"line two\"},\n"
                "data: \"finish_reason\":\"stop\"}]}\n\n"
                "data: [DONE]\n\n"
            ),
        )
        self.assertEqual(response.content, "line two")
        self.assertEqual(response.stop_reason, "stop")

    def test_parse_streaming_response_skips_empty_event_frames(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        response = gateway._parse_streaming_response(
            model="Meta-Llama-3.1-70B-Instruct",
            operation="completion",
            payload="event: ping\nid: 1\nretry: 1\n\n",
        )
        self.assertEqual(response.content, "")
        self.assertIsNone(response.stop_reason)

    def test_parse_streaming_response_raises_for_malformed_json_event(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "Malformed SambaNova SSE frame payload"):
            gateway._parse_streaming_response(
                model="Meta-Llama-3.1-70B-Instruct",
                operation="completion",
                payload='data: {"choices": [}\n\n',
            )

    def test_parse_streaming_response_supports_delta_content_list(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        response = gateway._parse_streaming_response(
            model="Meta-Llama-3.1-70B-Instruct",
            operation="completion",
            payload=(
                'data: {"choices":[{"delta":{"content":[{"type":"output_text","text":"ok"}]},"finish_reason":"stop"}]}\n\n'
            ),
        )
        self.assertEqual(response.content, [{"type": "output_text", "text": "ok"}])
        self.assertEqual(
            response.vendor_fields.get("stream_content_deltas"),
            [{"type": "output_text", "text": "ok"}],
        )

    def test_parse_streaming_response_ignores_unsupported_delta_content_types(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        response = gateway._parse_streaming_response(
            model="Meta-Llama-3.1-70B-Instruct",
            operation="completion",
            payload='data: {"choices":[{"delta":{"content":123},"finish_reason":"stop"}]}\n\n',
        )
        self.assertEqual(response.content, "")
        self.assertEqual(response.stop_reason, "stop")

    def test_parse_sse_data_frames_supports_lines_without_colons_and_terminal_flush(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        self.assertEqual(
            gateway._parse_sse_data_frames(  # pylint: disable=protected-access
                operation="completion",
                payload="data\n",
            ),
            [""],
        )
        self.assertEqual(
            gateway._parse_sse_data_frames(  # pylint: disable=protected-access
                operation="completion",
                payload='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}',
            ),
            ['{"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}'],
        )

    def test_parse_sse_data_frames_rejects_empty_field_name(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "empty field name"):
            gateway._parse_sse_data_frames(  # pylint: disable=protected-access
                operation="completion",
                payload=" :value\n\n",
            )

    def test_parse_sse_data_frames_ignores_blank_lines_without_active_event(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        self.assertEqual(
            gateway._parse_sse_data_frames(  # pylint: disable=protected-access
                operation="completion",
                payload="\n\n",
            ),
            [],
        )

    def test_normalize_content_returns_none_for_unsupported_types(self) -> None:
        self.assertIsNone(SambaNovaCompletionGateway._normalize_content(123))

    def test_perform_request(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())

        class _FakeCurl:
            URL = object()
            POSTFIELDS = object()
            HTTPHEADER = object()
            WRITEFUNCTION = object()

            def __init__(self) -> None:
                self._write_function = None

            def setopt(self, option, value) -> None:  # noqa: ANN001
                if option is self.WRITEFUNCTION:
                    self._write_function = value

            def perform(self) -> None:
                assert self._write_function is not None
                self._write_function(b'{"ok":true}')

            @staticmethod
            def getinfo(_code) -> int:  # noqa: ANN001
                return 201

            @staticmethod
            def close() -> None:
                return

        with patch("mugen.core.gateway.completion.sambanova.pycurl.Curl", _FakeCurl):
            status, body = gateway._perform_request(
                headers=["h: v"],
                body={"hello": "world"},
            )

        self.assertEqual(status, 201)
        self.assertEqual(body, '{"ok":true}')

    def test_usage_from_payload_handles_non_dict(self) -> None:
        self.assertIsNone(SambaNovaCompletionGateway._usage_from_payload(payload=None))

    def test_resolve_helpers(self) -> None:
        gateway = SambaNovaCompletionGateway(_make_config(), Mock())
        self.assertEqual(
            gateway._resolve_stream_options(  # pylint: disable=protected-access
                CompletionRequest(messages=[CompletionMessage(role="user", content="x")])
            ),
            {"include_usage": False},
        )
        self.assertEqual(
            gateway._resolve_stream_options(  # pylint: disable=protected-access
                CompletionRequest(
                    messages=[CompletionMessage(role="user", content="x")],
                    inference=CompletionInferenceConfig(
                        stream_options={"include_usage": True},
                    ),
                )
            ),
            {"include_usage": True},
        )
        self.assertEqual(
            SambaNovaCompletionGateway._resolve_stop_sequences(
                CompletionRequest(messages=[CompletionMessage(role="user", content="x")]),
                operation_config={"stop": "###"},
            ),
            ["###"],
        )
        self.assertEqual(
            SambaNovaCompletionGateway._resolve_stop_sequences(
                CompletionRequest(messages=[CompletionMessage(role="user", content="x")]),
                operation_config={"stop": ["A", 1, "B", ""]},
            ),
            ["A", "B"],
        )
        self.assertEqual(SambaNovaCompletionGateway._normalize_dict(None), {})
        self.assertEqual(
            SambaNovaCompletionGateway._normalize_content([{"a": 1}, 1]),
            [{"a": 1}],
        )
        self.assertEqual(
            SambaNovaCompletionGateway._normalize_list_of_dicts([{"a": 1}, 1]),
            [{"a": 1}],
        )
        self.assertTrue(
            SambaNovaCompletionGateway._is_expected_probe_validation_response(
                400,
                '{"error":{"message":"validation failed"}}',
            )
        )
        self.assertFalse(
            SambaNovaCompletionGateway._is_expected_probe_validation_response(
                401,
                '{"error":{"message":"unauthorized"}}',
            )
        )
        self.assertFalse(
            SambaNovaCompletionGateway._is_expected_probe_validation_response(
                400,
                '""',
            )
        )

    async def test_get_completion_rejects_removed_vendor_stream_override(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": "false"},
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "Removed legacy vendor param 'stream'",
            ):
                await gateway.get_completion(request)

    async def test_get_completion_rejects_invalid_include_usage_boolean(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"include_usage": "definitely"},
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "Removed legacy vendor param 'include_usage'",
            ):
                await gateway.get_completion(request)

    async def test_get_completion_rejects_invalid_inference_stream_boolean(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        gateway = SambaNovaCompletionGateway(config, logging_gateway)
        payload = '{"choices":[{"message":{"content":"ok"},"finish_reason":"stop"}]}'
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream="definitely"),  # type: ignore[arg-type]
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            with self.assertRaisesRegex(
                CompletionGatewayError,
                "Invalid boolean value for inference.stream",
            ):
                await gateway.get_completion(request)

    def test_timeout_parser_rejects_invalid_values_and_production_fail_fast(
        self,
    ) -> None:
        gateway = SambaNovaCompletionGateway.__new__(SambaNovaCompletionGateway)
        gateway._config = _make_config()  # pylint: disable=protected-access
        gateway._logging_gateway = Mock()  # pylint: disable=protected-access

        with self.assertRaisesRegex(RuntimeError, "SambaNovaCompletionGateway.timeout"):
            gateway._resolve_optional_positive_float("bad", "timeout")
        with self.assertRaisesRegex(RuntimeError, "SambaNovaCompletionGateway.timeout"):
            gateway._resolve_optional_positive_float(0, "timeout")

        config = _make_config()
        config.mugen = SimpleNamespace(environment="production")
        logging_gateway = Mock()
        with self.assertRaisesRegex(
            RuntimeError,
            "SambaNovaCompletionGateway: Missing required production configuration field\\(s\\): "
            "connect_timeout_seconds, read_timeout_seconds.",
        ):
            SambaNovaCompletionGateway(config, logging_gateway)

    def test_perform_request_applies_timeout_options(self) -> None:
        config = _make_config()
        config.sambanova.api.connect_timeout_seconds = 4
        config.sambanova.api.read_timeout_seconds = 7
        gateway = SambaNovaCompletionGateway(config, Mock())

        options: dict[object, object] = {}

        class _FakeCurl:
            URL = object()
            POSTFIELDS = object()
            HTTPHEADER = object()
            WRITEFUNCTION = object()

            def __init__(self) -> None:
                self._write_function = None

            def setopt(self, option, value) -> None:  # noqa: ANN001
                options[option] = value
                if option is self.WRITEFUNCTION:
                    self._write_function = value

            def perform(self) -> None:
                assert self._write_function is not None
                self._write_function(b'{"ok":true}')

            @staticmethod
            def getinfo(_code) -> int:  # noqa: ANN001
                return 200

            @staticmethod
            def close() -> None:
                return

        with patch("mugen.core.gateway.completion.sambanova.pycurl.Curl", _FakeCurl):
            gateway._perform_request(headers=["h: v"], body={"hello": "world"})  # pylint: disable=protected-access

        self.assertIn(
            4000,
            options.values(),
        )
        self.assertIn(
            7000,
            options.values(),
        )

    def test_perform_request_preserves_sub_second_timeouts(self) -> None:
        config = _make_config()
        config.sambanova.api.connect_timeout_seconds = 0.25
        config.sambanova.api.read_timeout_seconds = 0.5
        gateway = SambaNovaCompletionGateway(config, Mock())

        options: dict[object, object] = {}

        class _FakeCurl:
            URL = object()
            POSTFIELDS = object()
            HTTPHEADER = object()
            WRITEFUNCTION = object()

            def __init__(self) -> None:
                self._write_function = None

            def setopt(self, option, value) -> None:  # noqa: ANN001
                options[option] = value
                if option is self.WRITEFUNCTION:
                    self._write_function = value

            def perform(self) -> None:
                assert self._write_function is not None
                self._write_function(b'{"ok":true}')

            @staticmethod
            def getinfo(_code) -> int:  # noqa: ANN001
                return 200

            @staticmethod
            def close() -> None:
                return

        with patch("mugen.core.gateway.completion.sambanova.pycurl.Curl", _FakeCurl):
            gateway._perform_request(headers=["h: v"], body={"hello": "world"})  # pylint: disable=protected-access

        self.assertIn(250, options.values())
        self.assertIn(500, options.values())

    def test_production_with_timeouts_does_not_emit_missing_timeout_warnings(self) -> None:
        config = _make_config()
        config.mugen = SimpleNamespace(environment="production")
        config.sambanova.api.connect_timeout_seconds = 3
        config.sambanova.api.read_timeout_seconds = 5
        logging_gateway = Mock()

        SambaNovaCompletionGateway(config, logging_gateway)
        logging_gateway.warning.assert_not_called()

    def test_perform_request_sets_timeout_options_without_none_guard(self) -> None:
        import mugen.core.gateway.completion.sambanova as sambanova_mod  # pylint: disable=import-outside-toplevel

        config = _make_config()
        config.sambanova.api.connect_timeout_seconds = 3
        config.sambanova.api.read_timeout_seconds = 5
        gateway = SambaNovaCompletionGateway(config, Mock())

        options: dict[object, object] = {}

        class _FakeCurl:
            URL = object()
            POSTFIELDS = object()
            HTTPHEADER = object()
            WRITEFUNCTION = object()

            def __init__(self) -> None:
                self._write_function = None

            def setopt(self, option, value) -> None:  # noqa: ANN001
                options[option] = value
                if option is self.WRITEFUNCTION:
                    self._write_function = value

            def perform(self) -> None:
                assert self._write_function is not None
                self._write_function(b'{"ok":true}')

            @staticmethod
            def getinfo(_code) -> int:  # noqa: ANN001
                return 200

            @staticmethod
            def close() -> None:
                return

        with (
            patch("mugen.core.gateway.completion.sambanova.pycurl.Curl", _FakeCurl),
            patch(
                "mugen.core.gateway.completion.sambanova.to_timeout_milliseconds",
                return_value=None,
            ),
        ):
            gateway._perform_request(headers=["h: v"], body={"hello": "world"})  # pylint: disable=protected-access

        self.assertIn(
            sambanova_mod.pycurl.CONNECTTIMEOUT_MS,
            options,
        )
        self.assertIn(
            sambanova_mod.pycurl.TIMEOUT_MS,
            options,
        )
