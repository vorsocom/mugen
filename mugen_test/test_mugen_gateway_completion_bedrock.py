"""Unit tests for mugen.core.gateway.completion.bedrock.BedrockCompletionGateway."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionInferenceConfig,
    CompletionMessage,
    CompletionRequest,
)
from mugen.core.gateway.completion.bedrock import BedrockCompletionGateway


def _make_config() -> SimpleNamespace:
    return SimpleNamespace(
        aws=SimpleNamespace(
            bedrock=SimpleNamespace(
                api=SimpleNamespace(
                    region="us-east-1",
                    access_key_id="AKIA_TEST",
                    secret_access_key="SECRET_TEST",
                    dict={
                        "completion": {
                            "model": "anthropic.claude",
                            "max_tokens": "128",
                            "temp": "0.7",
                            "top_p": "0.9",
                        },
                    },
                )
            )
        )
    )


def _simple_request() -> CompletionRequest:
    return CompletionRequest(
        operation="completion",
        messages=[CompletionMessage(role="user", content="hello")],
    )


class TestMugenGatewayCompletionBedrock(unittest.IsolatedAsyncioTestCase):
    """Covers request shaping and failure handling for Bedrock completion."""

    class _StreamingBody:
        def __init__(self, payload: str) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return self._payload.encode("utf-8")

    @staticmethod
    def _build_request(
        *,
        model: str,
        vendor_params: dict | None = None,
    ) -> CompletionRequest:
        return CompletionRequest(
            operation="completion",
            model=model,
            messages=[
                CompletionMessage(role="system", content="sys"),
                CompletionMessage(role="user", content="hello"),
                CompletionMessage(role="assistant", content="hi"),
            ],
            inference=CompletionInferenceConfig(
                max_tokens=64,
                temperature=0.2,
                top_p=0.95,
                stop=["<END>"],
            ),
            vendor_params=vendor_params or {},
        )

    @staticmethod
    def _serialize_for_request(
        gateway: BedrockCompletionGateway,
        request: CompletionRequest,
    ) -> dict:
        conversation, system_prompts = gateway._split_messages(request)
        inference_config = gateway._build_inference_config(request, operation_config={})
        return gateway._serialize_invoke_body(
            request,
            model=request.model or "",
            conversation=conversation,
            system_prompts=system_prompts,
            inference_config=inference_config,
        )

    @staticmethod
    def _build_gateway(
        *,
        config: SimpleNamespace | None = None,
        bedrock_client: Mock | None = None,
    ) -> BedrockCompletionGateway:
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client or Mock(),
        ):
            return BedrockCompletionGateway(config or _make_config(), Mock())

    async def test_check_readiness_accepts_probe_validation_error(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.dict["classification"] = dict(
            config.aws.bedrock.api.dict["completion"]
        )
        bedrock_client = Mock()
        bedrock_client.invoke_model.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "ValidationException: malformed request body",
                }
            },
            operation_name="InvokeModel",
        )
        gateway = self._build_gateway(config=config, bedrock_client=bedrock_client)

        await gateway.check_readiness()

        bedrock_client.invoke_model.assert_called_once()

    async def test_check_readiness_raises_for_non_validation_probe_error(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.dict["classification"] = dict(
            config.aws.bedrock.api.dict["completion"]
        )
        bedrock_client = Mock()
        bedrock_client.invoke_model.side_effect = ClientError(
            {
                "Error": {
                    "Code": "AccessDeniedException",
                    "Message": "Access denied",
                }
            },
            operation_name="InvokeModel",
        )
        gateway = self._build_gateway(config=config, bedrock_client=bedrock_client)

        with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
            await gateway.check_readiness()

    async def test_check_readiness_raises_when_probe_model_missing(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.dict["completion"]["model"] = ""
        config.aws.bedrock.api.dict["classification"] = {"model": ""}
        gateway = self._build_gateway(config=config)

        with self.assertRaisesRegex(RuntimeError, "probe model is missing"):
            await gateway.check_readiness()

    async def test_check_readiness_defaults_timeout_when_nonpositive(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.dict["classification"] = dict(
            config.aws.bedrock.api.dict["completion"]
        )
        bedrock_client = Mock()
        bedrock_client.invoke_model.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "ValidationException: malformed request body",
                }
            },
            operation_name="InvokeModel",
        )
        gateway = self._build_gateway(config=config, bedrock_client=bedrock_client)
        gateway._read_timeout_seconds = 0  # pylint: disable=protected-access

        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.completion.bedrock.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()

        self.assertEqual(timeout_values, [10.0])

    async def test_check_readiness_uses_configured_positive_timeout(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.dict["classification"] = dict(
            config.aws.bedrock.api.dict["completion"]
        )
        bedrock_client = Mock()
        bedrock_client.invoke_model.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "ValidationException: malformed request body",
                }
            },
            operation_name="InvokeModel",
        )
        gateway = self._build_gateway(config=config, bedrock_client=bedrock_client)
        gateway._read_timeout_seconds = 4.0  # pylint: disable=protected-access

        timeout_values: list[float] = []

        async def _wait_for(awaitable, timeout):
            timeout_values.append(float(timeout))
            return await awaitable

        with patch(
            "mugen.core.gateway.completion.bedrock.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            await gateway.check_readiness()

        self.assertEqual(timeout_values, [4.0])

    async def test_check_readiness_wraps_non_client_errors(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.dict["classification"] = dict(
            config.aws.bedrock.api.dict["completion"]
        )
        gateway = self._build_gateway(config=config, bedrock_client=Mock())

        async def _wait_for(awaitable, timeout):
            _ = timeout
            await awaitable
            raise RuntimeError("probe boom")

        with patch(
            "mugen.core.gateway.completion.bedrock.asyncio.wait_for",
            side_effect=_wait_for,
        ):
            with self.assertRaisesRegex(RuntimeError, "readiness probe failed"):
                await gateway.check_readiness()

    async def test_get_completion_builds_messages_and_returns_trimmed_content(
        self,
    ) -> None:
        config = _make_config()
        logging_gateway = Mock()
        bedrock_client = Mock()
        bedrock_client.converse.return_value = {
            "output": {
                "message": {
                    "content": [
                        {
                            "text": "  hello world  ",
                        }
                    ]
                }
            }
        }

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ) as boto_client:
            gateway = BedrockCompletionGateway(config, logging_gateway)

        boto_client.assert_called_once_with(
            service_name="bedrock-runtime",
            region_name="us-east-1",
            aws_access_key_id="AKIA_TEST",
            aws_secret_access_key="SECRET_TEST",
        )

        response = await gateway.get_completion(
            CompletionRequest(
                operation="completion",
                messages=[
                    CompletionMessage(role="system", content="sys"),
                    CompletionMessage(role="user", content="hello"),
                    CompletionMessage(role="assistant", content="hi"),
                ],
            )
        )

        self.assertIsNotNone(response)
        self.assertEqual(response.content, "hello world")
        bedrock_client.converse.assert_called_once_with(
            modelId="anthropic.claude",
            messages=[
                {"role": "user", "content": [{"text": "hello"}]},
                {"role": "assistant", "content": [{"text": "hi"}]},
            ],
            system=[{"text": "sys"}],
            inferenceConfig={
                "maxTokens": 128,
                "temperature": 0.7,
                "topP": 0.9,
            },
        )

    async def test_get_completion_raises_gateway_error_on_exception(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        bedrock_client = Mock()
        bedrock_client.converse.side_effect = RuntimeError("boom")

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ):
            gateway = BedrockCompletionGateway(config, logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

        logging_gateway.warning.assert_called_once()

    async def test_get_completion_falls_back_to_invoke_model_when_needed(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        bedrock_client = Mock()
        bedrock_client.converse.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "Converse API is not supported for this model.",
                }
            },
            operation_name="Converse",
        )
        bedrock_client.invoke_model.return_value = {
            "body": self._StreamingBody(
                '{"content":[{"text":"invoke fallback output"}],"stop_reason":"end_turn"}'
            )
        }

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ):
            gateway = BedrockCompletionGateway(config, logging_gateway)

        response = await gateway.get_completion(_simple_request())

        self.assertEqual(response.content, "invoke fallback output")
        self.assertEqual(response.stop_reason, "end_turn")
        bedrock_client.converse.assert_called_once()
        bedrock_client.invoke_model.assert_called_once()

    def test_serialize_invoke_body_supports_amazon_nova(self) -> None:
        config = _make_config()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            gateway = BedrockCompletionGateway(config, Mock())

        request = self._build_request(
            model="amazon.nova-lite-v1:0",
            vendor_params={
                "top_k": 20,
                "additional_model_request_fields": {"thinking": {"type": "enabled"}},
                "tool_config": {"tools": [{"name": "my_tool"}]},
            },
        )
        body = self._serialize_for_request(gateway, request)

        self.assertEqual(body["schemaVersion"], "messages-v1")
        self.assertIn("system", body)
        self.assertEqual(body["inferenceConfig"]["maxTokens"], 64)
        self.assertEqual(body["inferenceConfig"]["topK"], 20)
        self.assertIn("additionalModelRequestFields", body)
        self.assertIn("toolConfig", body)

    def test_serialize_invoke_body_supports_openai_writer_and_ai21(self) -> None:
        config = _make_config()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            gateway = BedrockCompletionGateway(config, Mock())

        openai_body = self._serialize_for_request(
            gateway,
            self._build_request(model="openai.gpt-oss-20b-1:0"),
        )
        self.assertEqual(openai_body["max_completion_tokens"], 64)
        self.assertEqual(openai_body["messages"][0]["role"], "system")
        self.assertEqual(openai_body["stop"], ["<END>"])

        writer_body = self._serialize_for_request(
            gateway,
            self._build_request(model="writer.palmyra-x5-v1:0"),
        )
        self.assertEqual(writer_body["max_tokens"], 64)
        self.assertEqual(writer_body["messages"][1]["role"], "user")
        self.assertEqual(writer_body["top_p"], 0.95)

        jurassic_body = self._serialize_for_request(
            gateway,
            self._build_request(model="ai21.j2-ultra-v1"),
        )
        self.assertEqual(jurassic_body["maxTokens"], 64)
        self.assertIn("prompt", jurassic_body)

        jamba_body = self._serialize_for_request(
            gateway,
            self._build_request(model="ai21.jamba-1-5-large-v1:0"),
        )
        self.assertEqual(jamba_body["max_tokens"], 64)
        self.assertEqual(jamba_body["messages"][0]["role"], "system")

    def test_serialize_invoke_body_supports_cohere_command_r_and_deepseek(self) -> None:
        config = _make_config()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            gateway = BedrockCompletionGateway(config, Mock())

        cohere_body = self._serialize_for_request(
            gateway,
            self._build_request(model="cohere.command-r-v1:0"),
        )
        self.assertIn("message", cohere_body)
        self.assertEqual(cohere_body["max_tokens"], 64)
        self.assertEqual(cohere_body["p"], 0.95)

        deepseek_body = self._serialize_for_request(
            gateway,
            self._build_request(model="deepseek.r1-v1:0"),
        )
        self.assertEqual(deepseek_body["max_new_tokens"], 64)
        self.assertIn("prompt", deepseek_body)

    def test_parse_invoke_model_response_extracts_usage_for_openai_format(self) -> None:
        config = _make_config()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            gateway = BedrockCompletionGateway(config, Mock())

        request = self._build_request(model="openai.gpt-oss-20b-1:0")
        response = gateway._parse_invoke_model_response(
            request,
            model=request.model or "",
            payload={
                "choices": [
                    {
                        "message": {"content": "hello from openai"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 5,
                },
            },
            raw={},
        )

        self.assertEqual(response.content, "hello from openai")
        self.assertEqual(response.stop_reason, "stop")
        usage = response.usage
        self.assertIsNotNone(usage)
        if usage is not None:
            self.assertEqual(usage.total_tokens, 16)

    def test_parse_invoke_model_response_supports_nova_content_blocks(self) -> None:
        config = _make_config()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            gateway = BedrockCompletionGateway(config, Mock())

        request = self._build_request(model="amazon.nova-lite-v1:0")
        response = gateway._parse_invoke_model_response(
            request,
            model=request.model or "",
            payload={
                "output": {
                    "message": {
                        "content": [
                            {"text": "nova says hi"},
                            {"text": " and bye"},
                        ]
                    }
                },
                "stopReason": "end_turn",
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 7,
                    "totalTokens": 17,
                },
            },
            raw={},
        )

        self.assertEqual(response.content, "nova says hi and bye")
        self.assertEqual(response.stop_reason, "end_turn")
        self.assertIsNotNone(response.usage)

    async def test_get_completion_invoke_mode_wraps_client_error(self) -> None:
        bedrock_client = Mock()
        bedrock_client.invoke_model.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "Invalid input",
                }
            },
            operation_name="InvokeModel",
        )
        logging_gateway = Mock()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ):
            gateway = BedrockCompletionGateway(_make_config(), logging_gateway)

        request = self._build_request(
            model="anthropic.claude-v2",
            vendor_params={"bedrock_api": "invoke_model"},
        )
        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(request)

        logging_gateway.warning.assert_called_once()

    async def test_get_completion_invoke_mode_success(self) -> None:
        bedrock_client = Mock()
        bedrock_client.invoke_model.return_value = {
            "body": self._StreamingBody(
                '{"content":[{"text":"invoke mode"}],"stop_reason":"stop"}'
            )
        }
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ):
            gateway = BedrockCompletionGateway(_make_config(), Mock())

        request = self._build_request(
            model="anthropic.claude-v2",
            vendor_params={"bedrock_api": "invoke_model"},
        )
        response = await gateway.get_completion(request)
        self.assertEqual(response.content, "invoke mode")

    async def test_get_completion_converse_without_fallback_wraps_error(self) -> None:
        bedrock_client = Mock()
        bedrock_client.converse.side_effect = ClientError(
            {
                "Error": {
                    "Code": "ValidationException",
                    "Message": "Input is invalid",
                }
            },
            operation_name="Converse",
        )
        logging_gateway = Mock()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=bedrock_client,
        ):
            gateway = BedrockCompletionGateway(_make_config(), logging_gateway)

        with self.assertRaises(CompletionGatewayError):
            await gateway.get_completion(_simple_request())

    async def test_get_completion_rethrows_completion_gateway_error(self) -> None:
        config = _make_config()
        logging_gateway = Mock()
        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            gateway = BedrockCompletionGateway(config, logging_gateway)

        sentinel = CompletionGatewayError(
            provider="bedrock",
            operation="completion",
            message="already wrapped",
        )
        with patch.object(BedrockCompletionGateway, "_converse", side_effect=sentinel):
            with self.assertRaises(CompletionGatewayError) as context:
                await gateway.get_completion(_simple_request())

        self.assertIs(context.exception, sentinel)

    def test_resolve_operation_config_validation(self) -> None:
        gateway = self._build_gateway()
        with self.assertRaises(CompletionGatewayError):
            gateway._resolve_operation_config("missing")

        invalid_config = SimpleNamespace(
            aws=SimpleNamespace(
                bedrock=SimpleNamespace(
                    api=SimpleNamespace(
                        region="us-east-1",
                        access_key_id="AKIA_TEST",
                        secret_access_key="SECRET_TEST",
                        dict={"completion": "invalid"},
                    )
                )
            )
        )
        invalid_gateway = self._build_gateway(config=invalid_config)
        with self.assertRaises(CompletionGatewayError):
            invalid_gateway._resolve_operation_config("completion")

        missing_model_config = SimpleNamespace(
            aws=SimpleNamespace(
                bedrock=SimpleNamespace(
                    api=SimpleNamespace(
                        region="us-east-1",
                        access_key_id="AKIA_TEST",
                        secret_access_key="SECRET_TEST",
                        dict={"completion": {}},
                    )
                )
            )
        )
        missing_model_gateway = self._build_gateway(config=missing_model_config)
        with self.assertRaises(CompletionGatewayError):
            missing_model_gateway._resolve_operation_config("completion")

    def test_resolve_bedrock_mode_and_split_messages(self) -> None:
        self.assertEqual(
            BedrockCompletionGateway._resolve_bedrock_mode(
                self._build_request(model="anthropic.claude", vendor_params={})
            ),
            "auto",
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_bedrock_mode(
                self._build_request(
                    model="anthropic.claude",
                    vendor_params={"bedrock_api": "converse"},
                )
            ),
            "converse",
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_bedrock_mode(
                self._build_request(
                    model="anthropic.claude",
                    vendor_params={"bedrock_api": 123},
                )
            ),
            "auto",
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_bedrock_mode(
                self._build_request(
                    model="anthropic.claude",
                    vendor_params={"bedrock_api": "unexpected"},
                )
            ),
            "auto",
        )

        request = CompletionRequest(
            operation="completion",
            model="anthropic.claude",
            messages=[
                CompletionMessage(role="tool", content="tool message"),
                CompletionMessage(role="system", content="sys"),
            ],
            inference=CompletionInferenceConfig(),
        )
        conversation, system_prompts = BedrockCompletionGateway._split_messages(request)
        self.assertEqual(conversation[0]["role"], "user")
        self.assertIn("[tool]", conversation[0]["content"][0]["text"])
        self.assertEqual(system_prompts, [{"text": "sys"}])

    def test_build_inference_config_supports_empty_and_default_paths(self) -> None:
        gateway = self._build_gateway()
        request = CompletionRequest(
            operation="completion",
            model="anthropic.claude",
            messages=[CompletionMessage(role="user", content="hello")],
            inference=CompletionInferenceConfig(),
        )
        self.assertEqual(gateway._build_inference_config(request, {}), {})

        inferred = gateway._build_inference_config(
            request,
            {"max_tokens": "12", "temp": "0.3", "top_p": "0.7"},
        )
        self.assertEqual(inferred["maxTokens"], 12)
        self.assertEqual(inferred["temperature"], 0.3)
        self.assertEqual(inferred["topP"], 0.7)

    async def test_converse_applies_optional_fields_and_arn_rules(self) -> None:
        bedrock_client = Mock()
        bedrock_client.converse.return_value = {}
        gateway = self._build_gateway(bedrock_client=bedrock_client)

        request = self._build_request(
            model="anthropic.claude",
            vendor_params={
                "additional_model_request_fields": {"a": 1},
                "tool_config": {"tools": []},
                "guardrail_config": {"id": "g"},
                "prompt_variables": {"name": {"text": "x"}},
                "additional_model_response_field_paths": ["a.b"],
            },
        )
        conversation, system_prompts = gateway._split_messages(request)
        inference = gateway._build_inference_config(request, {})

        await gateway._converse(
            request,
            model="anthropic.claude",
            conversation=conversation,
            system_prompts=system_prompts,
            inference_config=inference,
        )
        kwargs = bedrock_client.converse.call_args.kwargs
        self.assertIn("system", kwargs)
        self.assertIn("inferenceConfig", kwargs)
        self.assertIn("additionalModelRequestFields", kwargs)
        self.assertIn("toolConfig", kwargs)
        self.assertIn("guardrailConfig", kwargs)
        self.assertIn("promptVariables", kwargs)
        self.assertIn("additionalModelResponseFieldPaths", kwargs)

        bedrock_client.converse.reset_mock()
        await gateway._converse(
            request,
            model="arn:aws:bedrock:us-east-1:123:prompt/test",
            conversation=conversation,
            system_prompts=system_prompts,
            inference_config=inference,
        )
        arn_kwargs = bedrock_client.converse.call_args.kwargs
        self.assertNotIn("system", arn_kwargs)
        self.assertNotIn("inferenceConfig", arn_kwargs)
        self.assertNotIn("additionalModelRequestFields", arn_kwargs)

        bedrock_client.converse.reset_mock()
        await gateway._converse(
            request,
            model="anthropic.claude",
            conversation=conversation,
            system_prompts=system_prompts,
            inference_config={},
        )
        kwargs_without_inference = bedrock_client.converse.call_args.kwargs
        self.assertNotIn("inferenceConfig", kwargs_without_inference)

    async def test_invoke_model_sets_accept_and_content_type(self) -> None:
        bedrock_client = Mock()
        bedrock_client.invoke_model.return_value = {
            "body": self._StreamingBody('{"generation":"ok","stop_reason":"stop"}')
        }
        gateway = self._build_gateway(bedrock_client=bedrock_client)
        request = self._build_request(
            model="meta.llama3",
            vendor_params={
                "bedrock_api": "invoke_model",
                "accept": "application/json",
                "content_type": "application/json",
            },
        )
        conversation, system_prompts = gateway._split_messages(request)
        inference = gateway._build_inference_config(request, {})

        result = await gateway._invoke_model(
            request,
            model="meta.llama3",
            conversation=conversation,
            system_prompts=system_prompts,
            inference_config=inference,
        )
        self.assertIn("payload", result)
        self.assertEqual(result["payload"]["generation"], "ok")

    def test_serialize_invoke_body_explicit_unknown_and_extra_fields(self) -> None:
        gateway = self._build_gateway()
        request = self._build_request(
            model="custom.model",
            vendor_params={
                "invoke_body": {"prompt": "x"},
                "invoke_extra_fields": {"custom": True},
            },
        )
        body = self._serialize_for_request(gateway, request)
        self.assertEqual(body["prompt"], "x")
        self.assertNotIn("custom", body)

        request_no_body = self._build_request(model="custom.model")
        with self.assertRaises(CompletionGatewayError):
            self._serialize_for_request(gateway, request_no_body)

    def test_serialize_invoke_body_supports_remaining_families(self) -> None:
        gateway = self._build_gateway()

        meta_body = self._serialize_for_request(
            gateway,
            self._build_request(model="meta.llama3-70b-instruct-v1:0"),
        )
        self.assertIn("max_gen_len", meta_body)

        titan_body = self._serialize_for_request(
            gateway,
            self._build_request(model="amazon.titan-text-express-v1"),
        )
        self.assertIn("textGenerationConfig", titan_body)

        cohere_body = self._serialize_for_request(
            gateway,
            self._build_request(model="cohere.command-text-v14"),
        )
        self.assertIn("prompt", cohere_body)

        mistral_chat_body = self._serialize_for_request(
            gateway,
            self._build_request(model="mistral.mistral-large-2407-v1:0"),
        )
        self.assertIn("messages", mistral_chat_body)

        mistral_prompt_body = self._serialize_for_request(
            gateway,
            self._build_request(model="mistral.mistral-7b-instruct-v0:2"),
        )
        self.assertIn("prompt", mistral_prompt_body)

    def test_family_resolution_and_defaults(self) -> None:
        request = self._build_request(
            model="ignored",
            vendor_params={"invoke_family": "command-r"},
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_invoke_family(
                request,
                model="unknown.model",
            ),
            "cohere_command_r",
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_invoke_family(
                self._build_request(model="mistral.mistral-large-v1:0"),
                model="mistral.mistral-large-v1:0",
            ),
            "mistral_chat",
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_invoke_family(
                self._build_request(model="unknown"),
                model="unknown",
            ),
            "unknown",
        )
        self.assertEqual(
            BedrockCompletionGateway._resolve_invoke_family(
                self._build_request(
                    model="anthropic.claude",
                    vendor_params={"invoke_family": "not-a-family"},
                ),
                model="anthropic.claude",
            ),
            "anthropic",
        )
        self.assertTrue(BedrockCompletionGateway._is_mistral_chat_model("ministral"))
        self.assertFalse(BedrockCompletionGateway._is_mistral_chat_model("mistral-7b"))

    def test_serializer_helpers_and_inference_merging(self) -> None:
        inference = {
            "maxTokens": 10,
            "temperature": 0.2,
            "topP": 0.9,
            "stopSequences": ["<END>"],
        }
        empty: dict = {}
        chat_messages = [{"role": "user", "content": "hello"}]
        conversation = [{"role": "user", "content": [{"text": "hello"}]}]
        system_prompts = [{"text": "sys"}]
        request = self._build_request(model="anthropic.claude")

        self.assertIn(
            "system",
            BedrockCompletionGateway._serialize_anthropic_invoke(
                request=request,
                conversation=conversation,
                system_prompts=system_prompts,
                inference_config=inference,
            ),
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_meta_invoke(
                prompt="p",
                inference_config=empty,
            ),
            {"prompt": "p"},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_titan_text_invoke(
                prompt="p",
                inference_config=empty,
            ),
            {"inputText": "p"},
        )
        self.assertIn(
            "topK",
            BedrockCompletionGateway._serialize_nova_invoke(
                request=self._build_request(
                    model="amazon.nova",
                    vendor_params={"top_k": 3},
                ),
                conversation=conversation,
                system_prompts=[],
                inference_config={},
            )["inferenceConfig"],
        )
        self.assertIn(
            "maxTokens",
            BedrockCompletionGateway._serialize_ai21_jurassic_invoke(
                prompt="p",
                inference_config=inference,
            ),
        )
        self.assertIn(
            "messages",
            BedrockCompletionGateway._serialize_ai21_jamba_invoke(
                chat_messages=chat_messages,
                inference_config=inference,
            ),
        )
        self.assertIn(
            "message",
            BedrockCompletionGateway._serialize_cohere_command_r_invoke(
                prompt="p",
                conversation=[],
                system_prompts=[],
                inference_config=empty,
            ),
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_cohere_command_invoke(
                prompt="p",
                inference_config=empty,
            ),
            {"prompt": "p"},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_mistral_chat_invoke(
                chat_messages=chat_messages,
                inference_config=empty,
            ),
            {"messages": chat_messages},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_mistral_prompt_invoke(
                prompt="p",
                inference_config=empty,
            ),
            {"prompt": "p"},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_deepseek_invoke(
                prompt="p",
                inference_config=empty,
            ),
            {"prompt": "p"},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_openai_chat_invoke(
                chat_messages=chat_messages,
                inference_config=empty,
            ),
            {"messages": chat_messages},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_writer_chat_invoke(
                chat_messages=chat_messages,
                inference_config=empty,
            ),
            {"messages": chat_messages},
        )

        body = {"a": 1}
        BedrockCompletionGateway._apply_invoke_extra_fields(
            request=self._build_request(
                model="anthropic.claude",
                vendor_params={"invoke_extra_fields": {"b": 2}},
            ),
            body=body,
        )
        self.assertEqual(body["b"], 2)

        custom = {}
        BedrockCompletionGateway._merge_inference_into_custom_body(custom, {})
        self.assertEqual(custom, {})
        BedrockCompletionGateway._merge_inference_into_custom_body(custom, inference)
        self.assertEqual(custom["max_tokens"], 10)

        anthropic_no_inference = BedrockCompletionGateway._serialize_anthropic_invoke(
            request=request,
            conversation=conversation,
            system_prompts=[],
            inference_config={},
        )
        self.assertNotIn("max_tokens", anthropic_no_inference)

        nova_without_topk = BedrockCompletionGateway._serialize_nova_invoke(
            request=self._build_request(model="amazon.nova"),
            conversation=conversation,
            system_prompts=[],
            inference_config={},
        )
        self.assertNotIn("inferenceConfig", nova_without_topk)

        self.assertEqual(
            BedrockCompletionGateway._serialize_ai21_jurassic_invoke(
                prompt="p",
                inference_config={},
            ),
            {"prompt": "p"},
        )
        self.assertEqual(
            BedrockCompletionGateway._serialize_ai21_jamba_invoke(
                chat_messages=chat_messages,
                inference_config={},
            ),
            {"messages": chat_messages},
        )

        partial = {}
        BedrockCompletionGateway._merge_inference_into_custom_body(
            partial,
            {"maxTokens": 1},
        )
        self.assertEqual(partial, {"max_tokens": 1})

        partial_without_max = {}
        BedrockCompletionGateway._merge_inference_into_custom_body(
            partial_without_max,
            {"temperature": 0.6},
        )
        self.assertEqual(partial_without_max, {"temperature": 0.6})

    def test_parse_helpers_and_defaults(self) -> None:
        gateway = self._build_gateway()
        response = gateway._parse_converse_response(
            model="anthropic.claude",
            payload={
                "output": {"message": {"content": [{"text": "hello"}]}},
                "usage": {"inputTokens": 1, "outputTokens": 2, "totalTokens": 3},
                "stopReason": "end_turn",
                "additionalModelResponseFields": {"x": 1},
            },
        )
        self.assertEqual(response.content, "hello")
        self.assertEqual(response.vendor_fields["additionalModelResponseFields"], {"x": 1})

        payload = {"choices": [{"text": "fallback", "stop_reason": "length"}], "usage": {}}
        invoke_request = self._build_request(
            model="deepseek.r1-v1:0",
            vendor_params={
                "invoke_response_paths": ["missing.path", "choices.0.text"],
                "invoke_stop_reason_paths": ["missing", "choices.0.stop_reason"],
            },
        )
        parsed = gateway._parse_invoke_model_response(
            invoke_request,
            model="deepseek.r1-v1:0",
            payload=payload,
            raw={},
        )
        self.assertEqual(parsed.content, "fallback")
        self.assertEqual(parsed.stop_reason, "length")

        empty_path_response = gateway._parse_invoke_model_response(
            self._build_request(
                model="openai.gpt",
                vendor_params={
                    "invoke_response_paths": [],
                    "invoke_stop_reason_paths": [],
                },
            ),
            model="openai.gpt",
            payload={"usage": {"total_tokens": 1}},
            raw={},
        )
        self.assertEqual(empty_path_response.content, "")
        self.assertIsNone(empty_path_response.stop_reason)

        self.assertIsNone(BedrockCompletionGateway._extract_path({"a": [1]}, "a.9"))
        self.assertIsNone(BedrockCompletionGateway._extract_path({"a": 1}, "a.b"))
        self.assertIsNone(BedrockCompletionGateway._extract_path({"a": {}}, "a.b"))
        self.assertEqual(BedrockCompletionGateway._coerce_text_candidate([{"x": 1}]), None)
        self.assertEqual(
            BedrockCompletionGateway._coerce_text_candidate({"content": [{"text": "x"}]}),
            "x",
        )
        self.assertEqual(BedrockCompletionGateway._coerce_text_candidate({"x": 1}), None)

        usage = BedrockCompletionGateway._extract_usage(
            {"usage": {"prompt_tokens": 2, "output_tokens": 1}}
        )
        self.assertIsNotNone(usage)
        if usage is not None:
            self.assertEqual(usage.total_tokens, 3)
        self.assertIsNone(BedrockCompletionGateway._extract_usage({"usage": {}}))

        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("meta"),
            ["generation"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("amazon_titan_text"),
            ["results.0.outputText"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("ai21_jurassic"),
            ["completions.0.data.text"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("ai21_jamba"),
            ["choices.0.message.content", "choices.0.text"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("cohere_command_r"),
            ["text", "generations.0.text"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("cohere_command"),
            ["generations.0.text", "text"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("mistral_chat"),
            ["choices.0.message.content", "outputs.0.text"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("mistral_prompt"),
            ["outputs.0.text"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("deepseek"),
            ["choices.0.text", "choices.0.message.content"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_response_paths("unknown"),
            ["outputText", "completion"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("meta"),
            ["stop_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("amazon_titan_text"),
            ["results.0.completionReason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("ai21_jurassic"),
            ["completions.0.finishReason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("ai21_jamba"),
            ["choices.0.finish_reason", "finish_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("cohere_command_r"),
            ["finish_reason", "generations.0.finish_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("cohere_command"),
            ["generations.0.finish_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("mistral_chat"),
            ["choices.0.finish_reason", "outputs.0.stop_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("mistral_prompt"),
            ["outputs.0.stop_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("deepseek"),
            ["choices.0.stop_reason", "choices.0.finish_reason"],
        )
        self.assertEqual(
            BedrockCompletionGateway._default_stop_reason_paths("unknown"),
            ["stopReason"],
        )

    def test_error_helpers(self) -> None:
        error = ClientError(
            {"Error": {"Code": "ValidationException", "Message": "Converse unsupported"}},
            operation_name="Converse",
        )
        message = BedrockCompletionGateway._error_message_from_client_error(error)
        self.assertIn("ValidationException", message)

        self.assertTrue(BedrockCompletionGateway._should_fallback_to_invoke_model(error))
        self.assertFalse(
            BedrockCompletionGateway._should_fallback_to_invoke_model(
                ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "retry"}},
                    operation_name="Converse",
                )
            )
        )

    def test_constructor_applies_timeout_and_retry_config(self) -> None:
        config = _make_config()
        config.aws.bedrock.api.connect_timeout_seconds = 1.5
        config.aws.bedrock.api.read_timeout_seconds = 2.5
        config.aws.bedrock.api.max_attempts = 3

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ) as boto_client:
            BedrockCompletionGateway(config, Mock())

        _, kwargs = boto_client.call_args
        self.assertIn("config", kwargs)
        self.assertEqual(kwargs["config"].connect_timeout, 1.5)
        self.assertEqual(kwargs["config"].read_timeout, 2.5)

    def test_timeout_parsers_handle_invalid_and_non_positive_values(self) -> None:
        gateway = self._build_gateway()
        gateway._logging_gateway = Mock()

        self.assertIsNone(gateway._resolve_optional_positive_float("bad", "f"))
        self.assertIsNone(gateway._resolve_optional_positive_float(0, "f"))
        self.assertIsNone(gateway._resolve_optional_positive_int("bad", "i"))
        self.assertIsNone(gateway._resolve_optional_positive_int(0, "i"))
        self.assertGreaterEqual(gateway._logging_gateway.warning.call_count, 4)

    def test_constructor_raises_when_timeout_controls_missing_in_production(self) -> None:
        config = _make_config()
        config.mugen = SimpleNamespace(environment="production")
        logging_gateway = Mock()

        with (
            patch("mugen.core.gateway.completion.bedrock.boto3.client") as boto_client,
            self.assertRaisesRegex(
                RuntimeError,
                "BedrockCompletionGateway: Missing required production configuration field\\(s\\): "
                "connect_timeout_seconds, max_attempts, read_timeout_seconds.",
            ),
        ):
            BedrockCompletionGateway(config, logging_gateway)

        boto_client.assert_not_called()

    def test_production_with_timeout_controls_does_not_emit_missing_warnings(self) -> None:
        config = _make_config()
        config.mugen = SimpleNamespace(environment="production")
        config.aws.bedrock.api.connect_timeout_seconds = 1
        config.aws.bedrock.api.read_timeout_seconds = 2
        config.aws.bedrock.api.max_attempts = 3
        logging_gateway = Mock()

        with patch(
            "mugen.core.gateway.completion.bedrock.boto3.client",
            return_value=Mock(),
        ):
            BedrockCompletionGateway(config, logging_gateway)

        logging_gateway.warning.assert_not_called()
        self.assertFalse(
            BedrockCompletionGateway._should_fallback_to_invoke_model(
                ClientError(
                    {"Error": {"Code": "ValidationException", "Message": "bad input"}},
                    operation_name="Converse",
                )
            )
        )
