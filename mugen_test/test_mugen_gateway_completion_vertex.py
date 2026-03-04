"""Unit tests for mugen.core.gateway.completion.vertex.VertexCompletionGateway."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.vertex import VertexCompletionGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        gcp=SimpleNamespace(
            vertex=SimpleNamespace(
                api=SimpleNamespace(
                    project="proj-1",
                    location="us-central1",
                    access_token="vertex-static-token",
                    connect_timeout_seconds=2.0,
                    read_timeout_seconds=5.0,
                    dict={
                        "classification": {
                            "model": "gemini-2.0-flash-001",
                            "temp": 0.0,
                            "top_p": 1.0,
                            "max_completion_tokens": 1024,
                        },
                        "completion": {
                            "model": "gemini-2.0-flash-001",
                            "temp": 0.1,
                            "top_p": 0.9,
                            "max_completion_tokens": 128,
                        },
                    },
                ),
            ),
        )
    )


def _simple_request() -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
    )


class _FakeCurl:  # pylint: disable=too-few-public-methods
    """Simple pycurl fake used to capture request options and emit canned responses."""

    URL = "URL"
    POSTFIELDS = "POSTFIELDS"
    HTTPHEADER = "HTTPHEADER"
    WRITEFUNCTION = "WRITEFUNCTION"

    instances: list["_FakeCurl"] = []
    next_status_code = 200
    next_body = "{}"
    perform_side_effect: Exception | None = None

    def __init__(self) -> None:
        self.options: dict[object, object] = {}
        _FakeCurl.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.next_status_code = 200
        cls.next_body = "{}"
        cls.perform_side_effect = None

    def setopt(self, option, value) -> None:
        self.options[option] = value

    def perform(self) -> None:
        if _FakeCurl.perform_side_effect is not None:
            raise _FakeCurl.perform_side_effect
        writer = self.options.get(self.WRITEFUNCTION)
        if callable(writer):
            writer(str(_FakeCurl.next_body).encode("utf-8"))

    def getinfo(self, _code):
        return _FakeCurl.next_status_code

    def close(self) -> None:
        return None


class _FakeCredentials:  # pylint: disable=too-few-public-methods
    def __init__(self) -> None:
        self.valid = False
        self.token = ""
        self.refresh_calls = 0

    def refresh(self, _request) -> None:
        self.refresh_calls += 1
        self.valid = True
        self.token = "adc-refreshed-token"


class TestMugenGatewayCompletionVertex(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for Vertex completion."""

    def test_constructor_rejects_missing_location(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.location = ""
        with self.assertRaisesRegex(RuntimeError, "location is required"):
            VertexCompletionGateway(config, Mock())

    def test_constructor_raises_when_timeouts_missing_in_production(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.connect_timeout_seconds = None
        config.gcp.vertex.api.read_timeout_seconds = None
        config.mugen = SimpleNamespace(environment="production")

        with self.assertRaisesRegex(
            RuntimeError,
            (
                "VertexCompletionGateway: Missing required production configuration "
                "field\\(s\\): connect_timeout_seconds, read_timeout_seconds."
            ),
        ):
            VertexCompletionGateway(config, Mock())

    async def test_aclose_is_noop(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        self.assertIsNone(await gateway.aclose())

    def test_perform_request_uses_static_access_token(self) -> None:
        config = _make_config()
        gateway = VertexCompletionGateway(config, Mock())
        _FakeCurl.reset()

        with patch("mugen.core.gateway.completion.vertex.pycurl.Curl", _FakeCurl):
            status_code, body_text = gateway._perform_request(
                model="gemini-2.0-flash-001",
                body={"contents": [{"role": "user", "parts": [{"text": "hello"}]}]},
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(body_text, "{}")
        curl_instance = _FakeCurl.instances[0]
        headers = curl_instance.options[_FakeCurl.HTTPHEADER]
        self.assertIn("Authorization: Bearer vertex-static-token", headers)
        self.assertIn(
            "/projects/proj-1/locations/us-central1/publishers/google/models/gemini-2.0-flash-001:generateContent",
            curl_instance.options[_FakeCurl.URL],
        )

    def test_perform_request_uses_adc_when_access_token_is_missing(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.project = ""
        config.gcp.vertex.api.access_token = ""
        gateway = VertexCompletionGateway(config, Mock())
        credentials = _FakeCredentials()
        google_auth_module = SimpleNamespace(
            default=Mock(return_value=(credentials, "adc-project"))
        )
        transport_requests_module = SimpleNamespace(Request=lambda: object())

        def _import_module(name: str):
            if name == "google.auth":
                return google_auth_module
            if name == "google.auth.transport.requests":
                return transport_requests_module
            raise ModuleNotFoundError(name)

        import mugen.core.gateway.completion.vertex as vertex_mod  # pylint: disable=import-outside-toplevel

        _FakeCurl.reset()
        with (
            patch.object(vertex_mod.pycurl, "Curl", _FakeCurl),
            patch.object(vertex_mod.importlib, "import_module", side_effect=_import_module),
        ):
            status_code, _ = gateway._perform_request(
                model="gemini-2.0-flash-001",
                body={"contents": [{"role": "user", "parts": [{"text": "hello"}]}]},
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(credentials.refresh_calls, 1)
        curl_instance = _FakeCurl.instances[0]
        headers = curl_instance.options[_FakeCurl.HTTPHEADER]
        self.assertIn("Authorization: Bearer adc-refreshed-token", headers)
        self.assertIn(
            "/projects/adc-project/locations/us-central1/publishers/google/models/gemini-2.0-flash-001:generateContent",
            curl_instance.options[_FakeCurl.URL],
        )

    def test_adc_import_failure_is_clear(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.access_token = ""
        gateway = VertexCompletionGateway(config, Mock())
        with patch(
            "mugen.core.gateway.completion.vertex.importlib.import_module",
            side_effect=ModuleNotFoundError("google.auth"),
        ):
            with self.assertRaisesRegex(RuntimeError, "requires google-auth"):
                gateway._resolve_access_token_sync()

    async def test_check_readiness_resolves_required_operation_configs(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(200, "{}"),
        ):
            await gateway.check_readiness()

    async def test_check_readiness_accepts_validation_style_probe_response(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(400, '{"error":{"message":"invalid request: contents is required"}}'),
        ):
            await gateway.check_readiness()

    async def test_check_readiness_fails_on_auth_error(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(401, '{"error":{"message":"Unauthorized"}}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "authentication error"):
                await gateway.check_readiness()

    async def test_check_readiness_wraps_transport_failures(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            side_effect=RuntimeError("transport down"),
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_check_readiness_rejects_legacy_max_tokens_config_key(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.dict["classification"]["max_tokens"] = 10
        gateway = VertexCompletionGateway(config, Mock())
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "includes removed legacy key 'max_tokens'",
        ):
            await gateway.check_readiness()

    async def test_get_completion_rejects_stream_requests(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream=True),
        )
        with self.assertRaisesRegex(CompletionGatewayError, "stream mode is not yet supported"):
            await gateway.get_completion(request)

    async def test_get_completion_rejects_removed_legacy_vendor_param(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"stream": True},
        )
        with self.assertRaisesRegex(
            CompletionGatewayError,
            "Removed legacy vendor param 'stream'",
        ):
            await gateway.get_completion(request)

    async def test_get_completion_maps_request_and_parses_text_response(self) -> None:
        config = _make_config()
        gateway = VertexCompletionGateway(config, Mock())
        captured: dict[str, object] = {}
        response_payload = (
            '{"candidates":[{"content":{"parts":[{"text":"hello world"}]},'
            '"finishReason":"STOP"}],'
            '"usageMetadata":{"promptTokenCount":11,"candidatesTokenCount":7,"totalTokenCount":18},'
            '"modelVersion":"gemini-2.0-flash-001"}'
        )
        request = CompletionRequest(
            operation="completion",
            messages=[
                CompletionMessage(role="system", content="sys"),
                CompletionMessage(role="user", content="hello"),
                CompletionMessage(role="assistant", content={"a": 1}),
                CompletionMessage(role="tool", content="trace"),
            ],
            inference=CompletionInferenceConfig(
                max_completion_tokens=64,
                temperature=0.3,
                top_p=0.2,
                stop=["<END>"],
            ),
            vendor_params={
                "safety_settings": [{"category": "HARM_CATEGORY_HATE_SPEECH"}],
                "tools": [{"functionDeclarations": []}],
                "tool_config": {"functionCallingConfig": {"mode": "AUTO"}},
                "cached_content": "cachedContents/abc123",
                "response_mime_type": "application/json",
                "response_schema": {"type": "object"},
                "candidate_count": 2,
            },
        )

        def _perform_request(*, model: str, body: dict) -> tuple[int, str]:
            captured["model"] = model
            captured["body"] = body
            return 200, response_payload

        with patch.object(VertexCompletionGateway, "_perform_request", side_effect=_perform_request):
            response = await gateway.get_completion(request)

        self.assertEqual(captured["model"], "gemini-2.0-flash-001")
        body = captured["body"]
        assert isinstance(body, dict)
        self.assertEqual(body["contents"][0]["role"], "user")
        self.assertEqual(body["contents"][1]["role"], "model")
        self.assertTrue(body["contents"][2]["parts"][0]["text"].startswith("[tool] "))
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "sys")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 64)
        self.assertEqual(body["generationConfig"]["temperature"], 0.3)
        self.assertEqual(body["generationConfig"]["topP"], 0.2)
        self.assertEqual(body["generationConfig"]["stopSequences"], ["<END>"])
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["responseSchema"], {"type": "object"})
        self.assertEqual(body["generationConfig"]["candidateCount"], 2)
        self.assertIn("safetySettings", body)
        self.assertIn("tools", body)
        self.assertIn("toolConfig", body)
        self.assertEqual(body["cachedContent"], "cachedContents/abc123")

        self.assertEqual(response.content, "hello world")
        self.assertEqual(response.stop_reason, "STOP")
        self.assertEqual(response.usage.input_tokens, 11)
        self.assertEqual(response.usage.output_tokens, 7)
        self.assertEqual(response.usage.total_tokens, 18)
        self.assertEqual(response.model, "gemini-2.0-flash-001")

    async def test_get_completion_parses_structured_tool_call_response(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        payload = (
            '{"candidates":[{"content":{"parts":['
            '{"functionCall":{"name":"lookup","args":{"id":1}}},'
            '{"inlineData":{"mimeType":"application/json","data":"e30="}}'
            ']},"finishReason":"STOP"}],'
            '"usageMetadata":{"promptTokenCount":4,"candidatesTokenCount":3,"totalTokenCount":7}}'
        )

        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(200, payload),
        ):
            response = await gateway.get_completion(_simple_request())

        self.assertIsInstance(response.content, list)
        self.assertEqual(response.tool_calls[0]["type"], "function")
        self.assertEqual(response.tool_calls[0]["function"]["name"], "lookup")
        self.assertEqual(response.tool_calls[0]["function"]["arguments"], '{"id": 1}')
        self.assertEqual(response.usage.total_tokens, 7)
        self.assertIn("structured_content_parts", response.vendor_fields)

    async def test_get_completion_rejects_invalid_candidate_count(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"candidate_count": 0},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "candidate_count must be greater than 0"):
            await gateway.get_completion(request)

    async def test_get_completion_raises_gateway_error_on_http_error(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(400, '{"error":{"code":400,"message":"bad request"}}'),
        ):
            with self.assertRaisesRegex(CompletionGatewayError, "400: bad request"):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_wraps_unexpected_transport_errors(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaisesRegex(CompletionGatewayError, "Failed to execute Vertex request"):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_wraps_invalid_json_payload(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(200, "not-json"),
        ):
            with self.assertRaisesRegex(CompletionGatewayError, "Failed to parse Vertex response payload"):
                await gateway.get_completion(_simple_request())

    async def test_get_completion_uses_operation_defaults(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.dict["completion"]["stop"] = ["A", "", 1, "B"]
        gateway = VertexCompletionGateway(config, Mock())
        captured_body: dict[str, Any] = {}

        def _perform_request(*, model: str, body: dict) -> tuple[int, str]:
            _ = model
            captured_body.update(body)
            return 200, '{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'

        with patch.object(VertexCompletionGateway, "_perform_request", side_effect=_perform_request):
            await gateway.get_completion(_simple_request())

        self.assertEqual(captured_body["generationConfig"]["maxOutputTokens"], 128)
        self.assertEqual(captured_body["generationConfig"]["temperature"], 0.1)
        self.assertEqual(captured_body["generationConfig"]["topP"], 0.9)
        self.assertEqual(captured_body["generationConfig"]["stopSequences"], ["A", "B"])

    def test_resolve_optional_api_string_returns_none_for_non_string(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.project = 123
        gateway = VertexCompletionGateway(config, Mock())
        self.assertIsNone(gateway._resolve_optional_api_string("project"))  # pylint: disable=protected-access

    async def test_check_readiness_raises_when_operation_model_is_missing(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.dict["classification"]["model"] = ""
        config.gcp.vertex.api.dict["completion"]["model"] = ""
        gateway = VertexCompletionGateway(config, Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "is missing model"):
            await gateway.check_readiness()

    async def test_check_readiness_uses_default_timeout_when_read_timeout_missing(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.read_timeout_seconds = None
        gateway = VertexCompletionGateway(config, Mock())
        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with (
            patch.object(VertexCompletionGateway, "_perform_request", return_value=(200, "{}")),
            patch("mugen.core.gateway.completion.vertex.asyncio.wait_for", side_effect=_wait_for),
        ):
            await gateway.check_readiness()

        self.assertEqual(timeout_values, [10.0])

    async def test_check_readiness_fails_on_provider_unavailable(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(503, '{"error":{"message":"unavailable"}}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
                await gateway.check_readiness()

    async def test_check_readiness_fails_on_unexpected_status(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_perform_request",
            return_value=(418, '{"error":{"message":"teapot"}}'),
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_get_completion_rethrows_completion_gateway_error(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        wrapped = CompletionGatewayError(
            provider="vertex",
            operation="completion",
            message="wrapped",
        )
        with patch.object(VertexCompletionGateway, "_perform_request", side_effect=wrapped):
            with self.assertRaises(CompletionGatewayError) as raised:
                await gateway.get_completion(_simple_request())
        self.assertIs(raised.exception, wrapped)

    def test_resolve_operation_config_handles_missing_invalid_and_missing_model(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "Missing Vertex operation configuration"):
            gateway._resolve_operation_config("unknown")  # pylint: disable=protected-access

        config = _make_config()
        config.gcp.vertex.api.dict["completion"] = "bad"
        gateway = VertexCompletionGateway(config, Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "Invalid Vertex operation configuration"):
            gateway._resolve_operation_config("completion")  # pylint: disable=protected-access

        config = _make_config()
        config.gcp.vertex.api.dict["completion"]["model"] = ""
        gateway = VertexCompletionGateway(config, Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "is missing model"):
            gateway._resolve_operation_config("completion")  # pylint: disable=protected-access

    async def test_get_completion_rejects_invalid_bool_like_stream_value(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(stream="maybe"),  # type: ignore[arg-type]
        )
        with self.assertRaisesRegex(CompletionGatewayError, "Invalid boolean value for inference.stream"):
            await gateway.get_completion(request)

    async def test_serialize_request_body_adds_default_contents_when_only_system_message(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        captured_body: dict[str, Any] = {}
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="system", content="sys-only")],
        )

        def _perform_request(*, model: str, body: dict) -> tuple[int, str]:
            _ = model
            captured_body.update(body)
            return 200, '{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'

        with patch.object(VertexCompletionGateway, "_perform_request", side_effect=_perform_request):
            await gateway.get_completion(request)

        self.assertEqual(captured_body["contents"], [{"role": "user", "parts": [{"text": ""}]}])
        self.assertIn("systemInstruction", captured_body)

    async def test_serialize_request_body_omits_empty_generation_config(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.dict["completion"] = {"model": "gemini-2.0-flash-001"}
        gateway = VertexCompletionGateway(config, Mock())
        captured_body: dict[str, Any] = {}

        def _perform_request(*, model: str, body: dict) -> tuple[int, str]:
            _ = model
            captured_body.update(body)
            return 200, '{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'

        with patch.object(VertexCompletionGateway, "_perform_request", side_effect=_perform_request):
            await gateway.get_completion(_simple_request())

        self.assertNotIn("generationConfig", captured_body)

    async def test_get_completion_rejects_non_integer_candidate_count(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="hello")],
            vendor_params={"candidate_count": "bad"},
        )
        with self.assertRaisesRegex(CompletionGatewayError, "candidate_count must be a positive integer"):
            await gateway.get_completion(request)

    def test_resolve_stop_sequences_supports_configured_string(self) -> None:
        request = CompletionRequest(
            operation="completion",
            messages=[CompletionMessage(role="user", content="x")],
        )
        self.assertEqual(
            VertexCompletionGateway._resolve_stop_sequences(
                request,
                operation_config={"stop": "###"},
            ),
            ["###"],
        )

    def test_serialize_text_content_handles_none_and_non_json_scalars(self) -> None:
        self.assertEqual(VertexCompletionGateway._serialize_text_content(None), "")
        self.assertEqual(VertexCompletionGateway._serialize_text_content(123), "123")

    def test_perform_request_handles_optional_timeout_branches(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.connect_timeout_seconds = None
        config.gcp.vertex.api.read_timeout_seconds = 5.0
        gateway = VertexCompletionGateway(config, Mock())
        _FakeCurl.reset()
        with patch("mugen.core.gateway.completion.vertex.pycurl.Curl", _FakeCurl):
            gateway._perform_request(  # pylint: disable=protected-access
                model="gemini-2.0-flash-001",
                body={"contents": [{"role": "user", "parts": [{"text": "x"}]}]},
            )
        read_only_options = _FakeCurl.instances[0].options
        self.assertNotIn("CONNECTTIMEOUT_MS", [str(k) for k in read_only_options])

        config = _make_config()
        config.gcp.vertex.api.connect_timeout_seconds = 2.0
        config.gcp.vertex.api.read_timeout_seconds = None
        gateway = VertexCompletionGateway(config, Mock())
        _FakeCurl.reset()
        with patch("mugen.core.gateway.completion.vertex.pycurl.Curl", _FakeCurl):
            gateway._perform_request(  # pylint: disable=protected-access
                model="gemini-2.0-flash-001",
                body={"contents": [{"role": "user", "parts": [{"text": "x"}]}]},
            )
        connect_only_options = _FakeCurl.instances[0].options
        self.assertNotIn("TIMEOUT_MS", [str(k) for k in connect_only_options])

    def test_build_endpoint_handles_projects_publishers_and_empty_model(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with self.assertRaisesRegex(RuntimeError, "model must be non-empty"):
            gateway._build_endpoint(model="  ")  # pylint: disable=protected-access

        endpoint = gateway._build_endpoint(model="projects/p/locations/l/publishers/google/models/m")  # pylint: disable=protected-access
        self.assertIn("/v1/projects/p/locations/l/publishers/google/models/m:generateContent", endpoint)

        endpoint = gateway._build_endpoint(model="publishers/google/models/gemini-2.0-flash-001")  # pylint: disable=protected-access
        self.assertIn("/v1/projects/proj-1/locations/us-central1/publishers/google/models/gemini-2.0-flash-001:generateContent", endpoint)

    def test_resolve_project_for_request_sync_raises_when_unavailable(self) -> None:
        config = _make_config()
        config.gcp.vertex.api.project = ""
        config.gcp.vertex.api.access_token = "token"
        gateway = VertexCompletionGateway(config, Mock())
        with self.assertRaisesRegex(RuntimeError, "requires gcp.vertex.api.project"):
            gateway._resolve_project_for_request_sync()  # pylint: disable=protected-access

    def test_resolve_access_token_sync_error_paths(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        gateway._static_access_token = None  # pylint: disable=protected-access
        gateway._ensure_adc_loaded_sync = lambda: None  # type: ignore[method-assign]  # pylint: disable=protected-access
        gateway._adc_credentials = None  # pylint: disable=protected-access
        gateway._adc_request_class = None  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "failed to initialize ADC credentials"):
            gateway._resolve_access_token_sync()  # pylint: disable=protected-access

        class _RefreshBoom:  # pylint: disable=too-few-public-methods
            valid = False
            token = ""

            @staticmethod
            def refresh(_request):
                raise RuntimeError("boom")

        gateway._adc_credentials = _RefreshBoom()  # pylint: disable=protected-access
        gateway._adc_request_class = lambda: object()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "failed to refresh ADC access token"):
            gateway._resolve_access_token_sync()  # pylint: disable=protected-access

        class _RefreshEmpty:  # pylint: disable=too-few-public-methods
            valid = False
            token = ""

            def refresh(self, _request):
                self.valid = True
                self.token = ""

        gateway._adc_credentials = _RefreshEmpty()  # pylint: disable=protected-access
        with self.assertRaisesRegex(RuntimeError, "could not resolve a non-empty access token"):
            gateway._resolve_access_token_sync()  # pylint: disable=protected-access

    def test_ensure_adc_loaded_sync_error_paths(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())

        class _PrepopulateLock:  # pylint: disable=too-few-public-methods
            def __init__(self, target):
                self._target = target

            def __enter__(self):
                self._target._adc_credentials = object()  # pylint: disable=protected-access
                self._target._adc_request_class = object()  # pylint: disable=protected-access
                return self

            def __exit__(self, exc_type, exc, tb):
                _ = exc_type
                _ = exc
                _ = tb
                return False

        gateway._adc_credentials = None  # pylint: disable=protected-access
        gateway._adc_request_class = None  # pylint: disable=protected-access
        gateway._adc_lock = _PrepopulateLock(gateway)  # type: ignore[assignment]  # pylint: disable=protected-access
        gateway._ensure_adc_loaded_sync()  # pylint: disable=protected-access

        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_import_google_auth_modules",
            return_value=(SimpleNamespace(default=lambda scopes: (object(), "proj")), SimpleNamespace(Request=None)),
        ):
            with self.assertRaisesRegex(RuntimeError, "failed to load google-auth request transport"):
                gateway._ensure_adc_loaded_sync()  # pylint: disable=protected-access

        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_import_google_auth_modules",
            return_value=(SimpleNamespace(default=Mock(side_effect=RuntimeError("boom"))), SimpleNamespace(Request=lambda: object())),
        ):
            with self.assertRaisesRegex(RuntimeError, "failed to load ADC credentials"):
                gateway._ensure_adc_loaded_sync()  # pylint: disable=protected-access

        gateway = VertexCompletionGateway(_make_config(), Mock())
        with patch.object(
            VertexCompletionGateway,
            "_import_google_auth_modules",
            return_value=(SimpleNamespace(default=lambda scopes: (object(), None)), SimpleNamespace(Request=lambda: object())),
        ):
            gateway._ensure_adc_loaded_sync()  # pylint: disable=protected-access
        self.assertIsNone(gateway._adc_project_id)  # pylint: disable=protected-access

    def test_extract_http_error_additional_branches(self) -> None:
        self.assertEqual(VertexCompletionGateway._extract_http_error("not-json"), "not-json")
        self.assertEqual(VertexCompletionGateway._extract_http_error('"x"'), "x")
        self.assertEqual(VertexCompletionGateway._extract_http_error('{"error":"bad"}'), "{'error': 'bad'}")

    def test_is_expected_probe_validation_response_additional_branches(self) -> None:
        self.assertFalse(VertexCompletionGateway._is_expected_probe_validation_response(200, "{}"))
        with patch.object(VertexCompletionGateway, "_extract_http_error", return_value=""):
            self.assertFalse(VertexCompletionGateway._is_expected_probe_validation_response(400, "{}"))
        self.assertFalse(
            VertexCompletionGateway._is_expected_probe_validation_response(
                400,
                '{"error":{"message":"forbidden permission denied"}}',
            )
        )
        self.assertFalse(
            VertexCompletionGateway._is_expected_probe_validation_response(
                400,
                '{"error":{"message":"model not found"}}',
            )
        )

    def test_parse_json_response_additional_branches(self) -> None:
        gateway = VertexCompletionGateway(_make_config(), Mock())
        with self.assertRaisesRegex(CompletionGatewayError, "did not include any completion candidates"):
            gateway._parse_json_response(model="m", operation="completion", payload={})  # pylint: disable=protected-access

        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "one"}]},
                    "finishReason": "STOP",
                    "safetyRatings": [{"category": "x"}],
                },
                {
                    "content": {"parts": [{"text": "two"}]},
                    "finishReason": "STOP",
                },
            ],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 2,
                "totalTokenCount": 3,
                "cacheHit": True,
            },
        }
        response = gateway._parse_json_response(  # pylint: disable=protected-access
            model="fallback-model",
            operation="completion",
            payload=payload,
        )
        self.assertEqual(response.model, "fallback-model")
        self.assertIn("additional_candidates", response.vendor_fields)
        self.assertIn("safety_ratings", response.vendor_fields)
        self.assertTrue(response.usage.vendor_fields["cacheHit"])

    def test_function_call_to_tool_call_additional_branches(self) -> None:
        from_string = VertexCompletionGateway._function_call_to_tool_call(  # pylint: disable=protected-access
            {"name": "a", "args": '{"x":1}', "id": "call-1"}
        )
        self.assertEqual(from_string["function"]["arguments"], '{"x":1}')
        self.assertEqual(from_string["id"], "call-1")

        from_none = VertexCompletionGateway._function_call_to_tool_call(  # pylint: disable=protected-access
            {"name": "a", "args": None}
        )
        self.assertEqual(from_none["function"]["arguments"], "{}")

    def test_normalize_helpers_additional_branches(self) -> None:
        self.assertEqual(VertexCompletionGateway._normalize_dict(1), {})
        self.assertEqual(VertexCompletionGateway._normalize_list_of_dicts("bad"), [])  # pylint: disable=protected-access
        self.assertEqual(
            VertexCompletionGateway._normalize_list_of_dicts([{"a": 1}, 1]),  # pylint: disable=protected-access
            [{"a": 1}],
        )


if __name__ == "__main__":
    unittest.main()
