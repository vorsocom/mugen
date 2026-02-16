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


class TestMugenGatewayCompletionSambaNova(unittest.IsolatedAsyncioTestCase):
    """Covers response parsing and failure handling for SambaNova completion."""

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
                [{"role": "user", "content": "hello"}],
            )

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)

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
            vendor_params={"stream": True},
        )

        with patch.object(
            SambaNovaCompletionGateway,
            "_perform_request",
            return_value=(200, stream_payload),
        ):
            response = await gateway.get_completion(request)

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "stop")

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
                await gateway.get_completion([{"role": "user", "content": "hello"}])

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
                max_tokens=42,
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
        self.assertEqual(body["max_tokens"], 42)
        self.assertEqual(body["frequency_penalty"], 0.2)
        self.assertEqual(body["presence_penalty"], 0.3)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["seed"], 123)
        self.assertEqual(body["tool_choice"], "none")
        self.assertEqual(body["tools"], [{"type": "function"}])
        self.assertEqual(body["user"], "u-1")

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
                await gateway.get_completion([{"role": "user", "content": "hello"}])

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
                await gateway.get_completion([{"role": "user", "content": "hello"}])

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

    def test_parse_streaming_response_handles_non_prefixed_chunks(self) -> None:
        config = _make_config()
        gateway = SambaNovaCompletionGateway(config, Mock())
        response = gateway._parse_streaming_response(
            model="Meta-Llama-3.1-70B-Instruct",
            operation="completion",
            payload='{"choices":[{"delta":{"content":123},"finish_reason":"stop"}]}\n\n',
        )
        self.assertEqual(response.content, "")
        self.assertEqual(response.stop_reason, "stop")

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
