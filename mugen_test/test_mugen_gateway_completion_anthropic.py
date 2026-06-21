"""Unit tests for AnthropicCompletionGateway."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from mugen.core.contract.gateway.completion import (
    CompletionContinuationState,
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionReasoningConfig,
    CompletionRequest,
    CompletionTool,
    CompletionToolResult,
)
from mugen.core.gateway.completion.anthropic import AnthropicCompletionGateway
from mugen.core.gateway.completion.anthropic_messages import (
    build_claude_messages_body,
    operation_config_uses_reasoning,
    parse_claude_messages_response,
    request_uses_claude_workflow_fields,
    serialize_claude_tool_result,
)


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        anthropic=SimpleNamespace(
            api=SimpleNamespace(
                base_url="https://anthropic.example.test",
                version="2023-06-01",
                key="anthropic-test-key",
                timeout_seconds=3.0,
                dict={
                    "classification": {
                        "model": "claude-sonnet-4-6",
                        "max_completion_tokens": 128,
                    },
                    "completion": {
                        "model": "claude-sonnet-4-6",
                        "max_completion_tokens": 512,
                        "temp": 0.2,
                        "top_p": 0.9,
                    },
                },
            )
        )
    )


class _FakeResponse:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def text(self) -> str:
        return self._body


class _FakeSession:
    def __init__(
        self, response: _FakeResponse | None = None, exc: Exception | None = None
    ):
        self.response = response or _FakeResponse(200, "{}")
        self.exc = exc
        self.closed = False
        self.calls: list[dict] = []

    def request(self, method: str, url: str, **kwargs):
        if self.exc is not None:
            raise self.exc
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return self.response

    async def close(self) -> None:
        self.closed = True


class TestMugenGatewayCompletionAnthropic(unittest.IsolatedAsyncioTestCase):
    """Covers direct Anthropic Messages gateway behavior."""

    @staticmethod
    def _gateway(config: SimpleNamespace | None = None) -> AnthropicCompletionGateway:
        return AnthropicCompletionGateway(config or _make_config(), Mock())

    async def test_get_completion_serializes_workflow_and_parses_response(self) -> None:
        gateway = self._gateway()
        payload = {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "redacted_thinking", "data": "redacted"},
                {"type": "text", "text": "Use the lookup."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "lookup",
                    "input": {"query": "alpha"},
                },
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 2,
            },
        }
        gateway._request_json = AsyncMock(
            return_value=payload
        )  # pylint: disable=protected-access

        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage(role="system", content="policy"),
                CompletionMessage(role="user", content="find alpha"),
            ],
            inference=CompletionInferenceConfig(stop=["DONE"]),
            reasoning=CompletionReasoningConfig(
                mode="adaptive",
                effort="medium",
                visibility="opaque",
            ),
            tools=[
                CompletionTool(
                    name="lookup",
                    description="Lookup data",
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                    provider_hints={
                        "anthropic": {"cache_control": {"type": "ephemeral"}}
                    },
                )
            ],
            continuation_state=CompletionContinuationState(
                provider="anthropic",
                thinking_blocks=[
                    {"type": "thinking", "thinking": "", "signature": "old-sig"}
                ],
                redacted_thinking_blocks=[
                    {"type": "redacted_thinking", "data": "old-redacted"}
                ],
                output_items=[
                    {
                        "type": "tool_use",
                        "id": "old_tool",
                        "name": "lookup",
                        "input": {"query": "old"},
                    }
                ],
            ),
            tool_results=[
                CompletionToolResult(
                    tool_call_id="old_tool",
                    name="lookup",
                    content={"result": "ok"},
                )
            ],
            vendor_params={"metadata": {"trace": "abc"}},
        )

        response = await gateway.get_completion(request)

        sent_body = gateway._request_json.await_args.kwargs[
            "body"
        ]  # pylint: disable=protected-access
        self.assertEqual(sent_body["system"], "policy")
        self.assertEqual(
            sent_body["thinking"], {"type": "adaptive", "display": "omitted"}
        )
        self.assertEqual(sent_body["output_config"], {"effort": "medium"})
        self.assertEqual(sent_body["stop_sequences"], ["DONE"])
        self.assertEqual(sent_body["metadata"], {"trace": "abc"})
        self.assertEqual(sent_body["tools"][0]["name"], "lookup")
        self.assertIn("cache_control", sent_body["tools"][0])
        self.assertEqual(sent_body["messages"][1]["role"], "assistant")
        self.assertEqual(sent_body["messages"][1]["content"][0]["signature"], "old-sig")
        self.assertEqual(sent_body["messages"][2]["content"][0]["type"], "tool_result")
        self.assertEqual(response.content, "Use the lookup.")
        self.assertEqual(response.stop_reason, "tool_use")
        self.assertEqual(response.tool_calls[0].id, "toolu_1")
        self.assertEqual(response.tool_calls[0].arguments, {"query": "alpha"})
        self.assertEqual(response.output_items[0]["type"], "text")
        self.assertIsNotNone(response.reasoning_state)
        if response.reasoning_state is not None:
            self.assertEqual(len(response.reasoning_state.thinking_blocks), 1)
            self.assertEqual(len(response.reasoning_state.redacted_thinking_blocks), 1)
        self.assertIsNotNone(response.usage)
        if response.usage is not None:
            self.assertEqual(response.usage.total_tokens, 15)
            self.assertEqual(response.usage.vendor_fields["cache_read_input_tokens"], 2)

    async def test_operation_reasoning_defaults_and_manual_budget(self) -> None:
        config = _make_config()
        config.anthropic.api.dict["completion"]["reasoning"] = {
            "mode": "enabled",
            "budget_tokens": 2048,
            "visibility": "summarized",
        }
        gateway = self._gateway(config)
        gateway._request_json = AsyncMock(  # pylint: disable=protected-access
            return_value={
                "id": "msg_1",
                "role": "assistant",
                "content": [{"type": "text", "text": "done"}],
            }
        )

        response = await gateway.get_completion(
            CompletionRequest(
                operation="completion",
                model="claude-sonnet-4-5",
                messages=[
                    CompletionMessage(role="tool", content={"trace": "tool-output"}),
                ],
            )
        )

        body = gateway._request_json.await_args.kwargs[
            "body"
        ]  # pylint: disable=protected-access
        self.assertEqual(
            body["thinking"],
            {"type": "enabled", "budget_tokens": 2048, "display": "summarized"},
        )
        self.assertEqual(
            body["messages"][0]["content"][0]["text"], '[tool] {"trace": "tool-output"}'
        )
        self.assertEqual(response.content, "done")

    async def test_rejects_streaming_and_invalid_stream_value(self) -> None:
        gateway = self._gateway()
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        with self.assertRaisesRegex(CompletionGatewayError, "stream mode"):
            await gateway.get_completion(request)

        invalid_request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": "not-bool"},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "Invalid boolean value"):
            await gateway.get_completion(invalid_request)

    async def test_model_capability_rejections_are_clear(self) -> None:
        gateway = self._gateway()
        cases = [
            (
                "claude-opus-4-7",
                CompletionReasoningConfig(mode="enabled", budget_tokens=1024),
                "manual thinking",
            ),
            (
                "claude-fable-5",
                CompletionReasoningConfig(mode="disabled"),
                "disabled thinking",
            ),
            (
                "claude-sonnet-4-5",
                CompletionReasoningConfig(mode="adaptive"),
                "adaptive thinking",
            ),
            (
                "claude-sonnet-4-6",
                CompletionReasoningConfig(mode="unexpected"),
                "Unsupported reasoning.mode",
            ),
        ]
        for model, reasoning, pattern in cases:
            with self.subTest(model=model):
                request = CompletionRequest(
                    operation="completion",
                    model=model,
                    messages=[CompletionMessage(role="user", content="hello")],
                    reasoning=reasoning,
                )
                with self.assertRaisesRegex(CompletionGatewayError, pattern):
                    await gateway.get_completion(request)

    async def test_readiness_aclose_and_request_json_transport_paths(self) -> None:
        gateway = self._gateway()
        gateway._request_json = AsyncMock(
            return_value={"data": []}
        )  # pylint: disable=protected-access
        await gateway.check_readiness()
        gateway._request_json.assert_awaited_once()  # pylint: disable=protected-access
        self.assertIsNone(await gateway.aclose())

        gateway._request_json = AsyncMock(  # pylint: disable=protected-access
            side_effect=CompletionGatewayError(
                provider="anthropic",
                operation="readiness",
                message="down",
            )
        )
        with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
            await gateway.check_readiness()

        fake_session = _FakeSession(_FakeResponse(200, '{"ok": true}'))
        gateway = self._gateway()
        with patch(
            "mugen.core.gateway.completion.anthropic.aiohttp.ClientSession",
            return_value=fake_session,
        ):
            parsed = await gateway._request_json(  # pylint: disable=protected-access
                "GET",
                "/v1/test",
                operation="completion",
            )
        self.assertEqual(parsed, {"ok": True})
        self.assertEqual(
            fake_session.calls[0]["url"], "https://anthropic.example.test/v1/test"
        )
        self.assertEqual(
            fake_session.calls[0]["kwargs"]["headers"]["x-api-key"],
            "anthropic-test-key",
        )
        self.assertIsNone(await gateway.aclose())
        self.assertTrue(fake_session.closed)

        fake_session = _FakeSession(_FakeResponse(200, ""))
        gateway = self._gateway()
        with patch(
            "mugen.core.gateway.completion.anthropic.aiohttp.ClientSession",
            return_value=fake_session,
        ):
            parsed = await gateway._request_json(  # pylint: disable=protected-access
                "POST",
                "/v1/messages",
                operation="completion",
                body={"hello": "world"},
            )
        self.assertEqual(parsed, {})
        self.assertEqual(
            fake_session.calls[0]["kwargs"]["headers"]["content-type"],
            "application/json",
        )

    async def test_request_json_error_paths(self) -> None:
        gateway = self._gateway()
        gateway._session = _FakeSession(  # pylint: disable=protected-access
            _FakeResponse(400, '{"error":{"message":"bad request"}}')
        )
        with self.assertRaisesRegex(CompletionGatewayError, "bad request"):
            await gateway._request_json(
                "POST", "/v1/messages", operation="completion"
            )  # pylint: disable=protected-access

        gateway._session = _FakeSession(
            _FakeResponse(200, "not-json")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(CompletionGatewayError, "not valid JSON"):
            await gateway._request_json(
                "POST", "/v1/messages", operation="completion"
            )  # pylint: disable=protected-access

        gateway._session = _FakeSession(
            _FakeResponse(200, "[]")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(CompletionGatewayError, "not an object"):
            await gateway._request_json(
                "POST", "/v1/messages", operation="completion"
            )  # pylint: disable=protected-access

        gateway._session = _FakeSession(
            exc=aiohttp.ClientConnectionError("down")
        )  # pylint: disable=protected-access
        with self.assertRaisesRegex(CompletionGatewayError, "request failed"):
            await gateway._request_json(
                "POST", "/v1/messages", operation="completion"
            )  # pylint: disable=protected-access

        self.assertEqual(
            AnthropicCompletionGateway._extract_error_message("plain failure"),
            "plain failure",
        )
        self.assertEqual(
            AnthropicCompletionGateway._extract_error_message('{"message":"top"}'),
            "top",
        )
        self.assertEqual(
            AnthropicCompletionGateway._extract_error_message("{}"),
            "{}",
        )
        self.assertEqual(
            AnthropicCompletionGateway._extract_error_message("[]"),
            "[]",
        )
        self.assertEqual(
            AnthropicCompletionGateway._extract_error_message(
                '{"error":{"message":1}}'
            ),
            '{"error":{"message":1}}',
        )

    async def test_config_validation_and_helper_predicates(self) -> None:
        gateway = self._gateway()
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config(
                "missing"
            )  # pylint: disable=protected-access

        config = _make_config()
        config.anthropic.api.dict["completion"] = "bad"
        with self.assertRaises(CompletionGatewayError):
            self._gateway(config)._resolve_operation_config(
                "completion"
            )  # pylint: disable=protected-access

        config = _make_config()
        config.anthropic.api.dict["completion"] = {}
        with self.assertRaises(CompletionGatewayError):
            self._gateway(config)._resolve_operation_config(
                "completion"
            )  # pylint: disable=protected-access

        config = _make_config()
        config.anthropic.api.dict["completion"]["max_tokens"] = 10
        with self.assertRaisesRegex(CompletionGatewayError, "removed legacy key"):
            self._gateway(config)._resolve_operation_config(
                "completion"
            )  # pylint: disable=protected-access

        self.assertTrue(
            request_uses_claude_workflow_fields(
                CompletionRequest(
                    messages=[CompletionMessage(role="user", content="hello")],
                    tools=[CompletionTool(name="tool")],
                )
            )
        )
        self.assertFalse(
            request_uses_claude_workflow_fields(
                CompletionRequest(
                    messages=[CompletionMessage(role="user", content="hello")],
                )
            )
        )
        self.assertTrue(
            operation_config_uses_reasoning(
                {"reasoning": {"mode": "adaptive", "effort": "low"}}
            )
        )
        self.assertFalse(
            operation_config_uses_reasoning({"reasoning": {"mode": "disabled"}})
        )

    def test_constructor_defaults_and_production_validation(self) -> None:
        config = _make_config()
        config.anthropic.api.base_url = ""
        config.anthropic.api.version = ""
        config.anthropic.api.timeout_seconds = None
        gateway = self._gateway(config)
        self.assertEqual(
            gateway._base_url, "https://api.anthropic.com"
        )  # pylint: disable=protected-access
        self.assertEqual(
            gateway._version, "2023-06-01"
        )  # pylint: disable=protected-access

        bad_config = _make_config()
        bad_config.anthropic.api.key = " "
        with self.assertRaisesRegex(RuntimeError, "anthropic.api.key"):
            self._gateway(bad_config)

        prod_config = _make_config()
        prod_config.mugen = SimpleNamespace(environment="production")
        prod_config.anthropic.api.timeout_seconds = None
        with self.assertRaisesRegex(RuntimeError, "timeout_seconds"):
            self._gateway(prod_config)

    def test_shared_claude_helper_edge_shapes(self) -> None:
        request = CompletionRequest(
            operation="completion",
            model="claude-sonnet-4-5",
            messages=[
                CompletionMessage(role="system", content=None),
                CompletionMessage(role="user", content=None),
                CompletionMessage(
                    role="assistant",
                    content=[{"type": "text", "text": "hi"}],
                ),
                CompletionMessage(role="tool", content=None),
                CompletionMessage(
                    role="tool",
                    content=[{"type": "image", "source": {}}],
                ),
                CompletionMessage(
                    role="user",
                    content={"type": "text", "text": "typed"},
                ),
                CompletionMessage(role="user", content=42),
            ],
            reasoning=CompletionReasoningConfig(mode="enabled", visibility="hidden"),
            tools=[
                CompletionTool(
                    name="bare",
                    provider_hints={
                        "bedrock_anthropic": {"cache_control": {"type": "ephemeral"}}
                    },
                )
            ],
            tool_results=[
                CompletionToolResult(
                    tool_call_id="tool_1",
                    content=[{"type": "text", "text": "bad"}],
                    is_error=True,
                )
            ],
        )
        body = build_claude_messages_body(
            request=request,
            operation_config={},
            model="claude-sonnet-4-5",
            provider="anthropic",
            provider_label="AnthropicCompletionGateway",
            timeout_applied=None,
        )

        self.assertEqual(body["model"], "claude-sonnet-4-5")
        self.assertNotIn("max_tokens", body)
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertNotIn("description", body["tools"][0])
        self.assertIn("cache_control", body["tools"][0])
        self.assertEqual(body["messages"][0]["role"], "assistant")
        self.assertEqual(body["messages"][1]["content"][0]["text"], "[tool]")
        self.assertEqual(body["messages"][2]["content"][0]["text"], "[tool]")
        self.assertEqual(body["messages"][4]["content"][0]["text"], "42")
        self.assertEqual(body["messages"][5]["content"][0]["is_error"], True)

        disabled = build_claude_messages_body(
            request=CompletionRequest(
                messages=[CompletionMessage(role="user", content="hello")],
                reasoning=CompletionReasoningConfig(mode="disabled"),
            ),
            operation_config={},
            model="claude-sonnet-4-5",
            provider="anthropic",
            provider_label="AnthropicCompletionGateway",
            timeout_applied=None,
        )
        self.assertNotIn("thinking", disabled)

        adaptive = build_claude_messages_body(
            request=CompletionRequest(
                messages=[CompletionMessage(role="user", content="hello")],
                reasoning=CompletionReasoningConfig(mode="adaptive"),
            ),
            operation_config={},
            model="claude-sonnet-4-6",
            provider="anthropic",
            provider_label="AnthropicCompletionGateway",
            timeout_applied=None,
        )
        self.assertEqual(
            adaptive["thinking"],
            {"type": "adaptive", "display": "omitted"},
        )
        self.assertNotIn("output_config", adaptive)

        self.assertEqual(
            serialize_claude_tool_result(
                CompletionToolResult(tool_call_id="tool_2", content=None)
            )["content"],
            "null",
        )

        empty = parse_claude_messages_response(
            payload={"content": "not-a-list", "usage": {}},
            model="fallback-model",
            provider="anthropic",
            raw={},
        )
        self.assertEqual(empty.content, "")
        self.assertEqual(empty.model, "fallback-model")
        self.assertIsNone(empty.usage)

        partial_usage = parse_claude_messages_response(
            payload={
                "model": "",
                "stop_reason": 123,
                "content": [{"text": "legacy"}],
                "usage": {"input_tokens": 7, "reasoning_tokens": 3},
            },
            model="fallback-model",
            provider="anthropic",
            raw={},
        )
        self.assertEqual(partial_usage.content, "legacy")
        self.assertEqual(partial_usage.stop_reason, "123")
        self.assertIsNotNone(partial_usage.usage)
        if partial_usage.usage is not None:
            self.assertIsNone(partial_usage.usage.total_tokens)
            self.assertEqual(partial_usage.usage.reasoning_tokens, 3)
