"""Provides an AWS Bedrock chat completion gateway."""

# https://aws.amazon.com/bedrock/

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
    normalise_completion_request,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.timeout_config import (
    resolve_optional_positive_float,
    resolve_optional_positive_int,
    warn_missing_in_production,
)


# pylint: disable=too-few-public-methods
class BedrockCompletionGateway(ICompletionGateway):
    """An AWS Bedrock chat completion gateway."""

    _provider = "bedrock"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway
        self._connect_timeout_seconds = self._resolve_optional_positive_float(
            getattr(self._config.aws.bedrock.api, "connect_timeout_seconds", None),
            "connect_timeout_seconds",
        )
        self._read_timeout_seconds = self._resolve_optional_positive_float(
            getattr(self._config.aws.bedrock.api, "read_timeout_seconds", None),
            "read_timeout_seconds",
        )
        self._max_attempts = self._resolve_optional_positive_int(
            getattr(self._config.aws.bedrock.api, "max_attempts", None),
            "max_attempts",
        )

        boto_config_kwargs: dict[str, Any] = {}
        if self._connect_timeout_seconds is not None:
            boto_config_kwargs["connect_timeout"] = self._connect_timeout_seconds
        if self._read_timeout_seconds is not None:
            boto_config_kwargs["read_timeout"] = self._read_timeout_seconds
        if self._max_attempts is not None:
            boto_config_kwargs["retries"] = {
                "max_attempts": self._max_attempts,
                "mode": "standard",
            }
        boto_config = BotoConfig(**boto_config_kwargs) if boto_config_kwargs else None

        client_kwargs: dict[str, Any] = {
            "service_name": "bedrock-runtime",
            "region_name": self._config.aws.bedrock.api.region,
            "aws_access_key_id": self._config.aws.bedrock.api.access_key_id,
            "aws_secret_access_key": self._config.aws.bedrock.api.secret_access_key,
        }
        if boto_config is not None:
            client_kwargs["config"] = boto_config
        self._client = boto3.client(**client_kwargs)
        self._warn_missing_timeout_controls_in_production()

    def _resolve_optional_positive_float(
        self,
        value: Any,
        field_name: str,
    ) -> float | None:
        return resolve_optional_positive_float(
            value=value,
            field_name=field_name,
            provider_label="BedrockCompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _resolve_optional_positive_int(
        self,
        value: Any,
        field_name: str,
    ) -> int | None:
        return resolve_optional_positive_int(
            value=value,
            field_name=field_name,
            provider_label="BedrockCompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _warn_missing_timeout_controls_in_production(self) -> None:
        warn_missing_in_production(
            config=self._config,
            provider_label="BedrockCompletionGateway",
            logging_gateway=self._logging_gateway,
            field_values={
                "connect_timeout_seconds": self._connect_timeout_seconds,
                "read_timeout_seconds": self._read_timeout_seconds,
                "max_attempts": self._max_attempts,
            },
        )

    async def get_completion(
        self,
        request: CompletionRequest | list[dict[str, Any]],
        operation: str = "completion",
    ) -> CompletionResponse:
        completion_request = normalise_completion_request(request, operation=operation)
        operation_config = self._resolve_operation_config(completion_request.operation)
        model = completion_request.model or operation_config["model"]
        mode = self._resolve_bedrock_mode(completion_request)

        conversation, system_prompts = self._split_messages(completion_request)
        inference_config = self._build_inference_config(
            completion_request,
            operation_config,
        )

        try:
            if mode == "invoke_model":
                completion = await self._invoke_model(
                    completion_request,
                    model=model,
                    conversation=conversation,
                    system_prompts=system_prompts,
                    inference_config=inference_config,
                )
                return self._parse_invoke_model_response(
                    completion_request,
                    model=model,
                    payload=completion["payload"],
                    raw=completion["raw"],
                )

            try:
                completion = await self._converse(
                    completion_request,
                    model=model,
                    conversation=conversation,
                    system_prompts=system_prompts,
                    inference_config=inference_config,
                )
                return self._parse_converse_response(model=model, payload=completion)
            except ClientError as e:
                if mode == "converse" or not self._should_fallback_to_invoke_model(e):
                    raise

                self._logging_gateway.warning(
                    "BedrockCompletionGateway.get_completion: "
                    "Converse is not supported for this model. Falling back to "
                    "InvokeModel."
                )
                completion = await self._invoke_model(
                    completion_request,
                    model=model,
                    conversation=conversation,
                    system_prompts=system_prompts,
                    inference_config=inference_config,
                )
                return self._parse_invoke_model_response(
                    completion_request,
                    model=model,
                    payload=completion["payload"],
                    raw=completion["raw"],
                )
        except ClientError as e:
            message = self._error_message_from_client_error(e)
            self._logging_gateway.warning(
                "BedrockCompletionGateway.get_completion: "
                f"Bedrock API request failed ({message})."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=message,
                cause=e,
                timeout_applied=self._read_timeout_seconds,
            ) from e
        except CompletionGatewayError:
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "BedrockCompletionGateway.get_completion: "
                "Unexpected failure while processing completion request."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Unexpected Bedrock completion failure.",
                cause=e,
                timeout_applied=self._read_timeout_seconds,
            ) from e

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._config.aws.bedrock.api.dict[operation]
        except (AttributeError, KeyError) as e:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing Bedrock operation configuration: {operation}",
                cause=e,
            ) from e

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid Bedrock operation configuration: {operation}",
            )

        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Bedrock operation '{operation}' is missing model.",
            )

        return cfg

    @staticmethod
    def _resolve_bedrock_mode(request: CompletionRequest) -> str:
        mode = request.vendor_params.get("bedrock_api", "auto")
        if not isinstance(mode, str):
            return "auto"

        lowered = mode.strip().lower()
        if lowered in {"auto", "converse", "invoke_model"}:
            return lowered
        return "auto"

    def _build_inference_config(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> dict[str, Any]:
        inference_config: dict[str, Any] = {}

        max_tokens = request.inference.max_tokens
        if max_tokens is None and "max_tokens" in operation_config:
            max_tokens = int(operation_config["max_tokens"])
        if max_tokens is not None:
            inference_config["maxTokens"] = int(max_tokens)

        temperature = request.inference.temperature
        if temperature is None and "temp" in operation_config:
            temperature = float(operation_config["temp"])
        if temperature is not None:
            inference_config["temperature"] = float(temperature)

        top_p = request.inference.top_p
        if top_p is None and "top_p" in operation_config:
            top_p = float(operation_config["top_p"])
        if top_p is not None:
            inference_config["topP"] = float(top_p)

        if request.inference.stop:
            inference_config["stopSequences"] = request.inference.stop

        return inference_config

    @staticmethod
    def _split_messages(request: CompletionRequest) -> tuple[list[dict], list[dict]]:
        conversation: list[dict] = []
        system_prompts: list[dict] = []
        for message in request.messages:
            if message.role == "system":
                system_prompts.append({"text": message.content})
                continue

            if message.role in {"user", "assistant"}:
                role = message.role
                content = message.content
            else:
                role = "user"
                content = f"[{message.role}] {message.content}"

            conversation.append({"role": role, "content": [{"text": content}]})

        return conversation, system_prompts

    async def _converse(
        self,
        request: CompletionRequest,
        *,
        model: str,
        conversation: list[dict],
        system_prompts: list[dict],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "modelId": model,
            "messages": conversation,
        }

        # Prompt-management requests do not allow these fields.
        if not model.startswith("arn:"):
            if system_prompts:
                args["system"] = system_prompts
            if inference_config:
                args["inferenceConfig"] = inference_config

            additional_request_fields = request.vendor_params.get(
                "additional_model_request_fields"
            )
            if (
                isinstance(additional_request_fields, dict)
                and additional_request_fields
            ):
                args["additionalModelRequestFields"] = additional_request_fields

        tool_config = request.vendor_params.get("tool_config")
        if isinstance(tool_config, dict) and tool_config:
            args["toolConfig"] = tool_config

        guardrail_config = request.vendor_params.get("guardrail_config")
        if isinstance(guardrail_config, dict) and guardrail_config:
            args["guardrailConfig"] = guardrail_config

        prompt_variables = request.vendor_params.get("prompt_variables")
        if isinstance(prompt_variables, dict) and prompt_variables:
            args["promptVariables"] = prompt_variables

        response_paths = request.vendor_params.get(
            "additional_model_response_field_paths"
        )
        if isinstance(response_paths, list) and response_paths:
            args["additionalModelResponseFieldPaths"] = response_paths

        return await asyncio.to_thread(self._client.converse, **args)

    async def _invoke_model(
        self,
        request: CompletionRequest,
        *,
        model: str,
        conversation: list[dict],
        system_prompts: list[dict],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body = self._serialize_invoke_body(
            request,
            model=model,
            conversation=conversation,
            system_prompts=system_prompts,
            inference_config=inference_config,
        )

        accept = request.vendor_params.get("accept", "application/json")
        content_type = request.vendor_params.get("content_type", "application/json")

        response = await asyncio.to_thread(
            self._client.invoke_model,
            modelId=model,
            body=json.dumps(body),
            accept=accept,
            contentType=content_type,
        )
        payload = json.loads(response["body"].read())
        return {"payload": payload, "raw": response}

    def _serialize_invoke_body(
        self,
        request: CompletionRequest,
        *,
        model: str,
        conversation: list[dict],
        system_prompts: list[dict],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        explicit_body = request.vendor_params.get("invoke_body")
        if isinstance(explicit_body, dict):
            body = dict(explicit_body)
            self._merge_inference_into_custom_body(body, inference_config)
            return body

        family = self._resolve_invoke_family(request, model=model)
        prompt = self._messages_to_prompt(conversation, system_prompts)
        chat_messages = self._to_chat_messages(conversation, system_prompts)

        if family == "anthropic":
            body = self._serialize_anthropic_invoke(
                request=request,
                conversation=conversation,
                system_prompts=system_prompts,
                inference_config=inference_config,
            )
        elif family == "meta":
            body = self._serialize_meta_invoke(
                prompt=prompt,
                inference_config=inference_config,
            )
        elif family == "amazon_titan_text":
            body = self._serialize_titan_text_invoke(
                prompt=prompt,
                inference_config=inference_config,
            )
        elif family == "amazon_nova":
            body = self._serialize_nova_invoke(
                request=request,
                conversation=conversation,
                system_prompts=system_prompts,
                inference_config=inference_config,
            )
        elif family == "ai21_jurassic":
            body = self._serialize_ai21_jurassic_invoke(
                prompt=prompt,
                inference_config=inference_config,
            )
        elif family == "ai21_jamba":
            body = self._serialize_ai21_jamba_invoke(
                chat_messages=chat_messages,
                inference_config=inference_config,
            )
        elif family == "cohere_command_r":
            body = self._serialize_cohere_command_r_invoke(
                prompt=prompt,
                conversation=conversation,
                system_prompts=system_prompts,
                inference_config=inference_config,
            )
        elif family == "cohere_command":
            body = self._serialize_cohere_command_invoke(
                prompt=prompt,
                inference_config=inference_config,
            )
        elif family == "mistral_chat":
            body = self._serialize_mistral_chat_invoke(
                chat_messages=chat_messages,
                inference_config=inference_config,
            )
        elif family == "mistral_prompt":
            body = self._serialize_mistral_prompt_invoke(
                prompt=prompt,
                inference_config=inference_config,
            )
        elif family == "deepseek":
            body = self._serialize_deepseek_invoke(
                prompt=prompt,
                inference_config=inference_config,
            )
        elif family == "openai_chat":
            body = self._serialize_openai_chat_invoke(
                chat_messages=chat_messages,
                inference_config=inference_config,
            )
        elif family == "writer_chat":
            body = self._serialize_writer_chat_invoke(
                chat_messages=chat_messages,
                inference_config=inference_config,
            )
        else:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=(
                    "InvokeModel fallback for this Bedrock model requires "
                    "vendor_params['invoke_body'] or vendor_params['invoke_family']."
                ),
            )

        self._apply_invoke_extra_fields(request, body)
        return body

    @staticmethod
    def _resolve_invoke_family(request: CompletionRequest, *, model: str) -> str:
        family_override = request.vendor_params.get("invoke_family")
        if isinstance(family_override, str):
            normalised = family_override.strip().lower().replace("-", "_")
            aliases = {
                "anthropic": "anthropic",
                "meta": "meta",
                "amazon_titan_text": "amazon_titan_text",
                "titan_text": "amazon_titan_text",
                "amazon_nova": "amazon_nova",
                "nova": "amazon_nova",
                "ai21_jurassic": "ai21_jurassic",
                "ai21_j2": "ai21_jurassic",
                "jurassic": "ai21_jurassic",
                "ai21_jamba": "ai21_jamba",
                "jamba": "ai21_jamba",
                "cohere_command": "cohere_command",
                "cohere_command_r": "cohere_command_r",
                "command_r": "cohere_command_r",
                "mistral_chat": "mistral_chat",
                "mistral_prompt": "mistral_prompt",
                "deepseek": "deepseek",
                "openai_chat": "openai_chat",
                "openai": "openai_chat",
                "writer_chat": "writer_chat",
                "writer": "writer_chat",
            }
            if normalised in aliases:
                return aliases[normalised]

        model_lower = model.lower()
        if model_lower.startswith("anthropic."):
            return "anthropic"
        if model_lower.startswith("meta."):
            return "meta"
        if model_lower.startswith("amazon.titan-text"):
            return "amazon_titan_text"
        if model_lower.startswith("amazon.nova"):
            return "amazon_nova"
        if model_lower.startswith("ai21.j2"):
            return "ai21_jurassic"
        if model_lower.startswith("ai21.jamba"):
            return "ai21_jamba"
        if model_lower.startswith("cohere.command-r"):
            return "cohere_command_r"
        if model_lower.startswith("cohere."):
            return "cohere_command"
        if model_lower.startswith("mistral."):
            if BedrockCompletionGateway._is_mistral_chat_model(model_lower):
                return "mistral_chat"
            return "mistral_prompt"
        if model_lower.startswith("deepseek."):
            return "deepseek"
        if model_lower.startswith("openai."):
            return "openai_chat"
        if model_lower.startswith("writer."):
            return "writer_chat"
        return "unknown"

    @staticmethod
    def _is_mistral_chat_model(model_lower: str) -> bool:
        return any(
            marker in model_lower
            for marker in [
                "mistral-large",
                "pixtral-large",
                "ministral",
            ]
        )

    @staticmethod
    def _to_chat_messages(
        conversation: list[dict],
        system_prompts: list[dict],
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for prompt in system_prompts:
            messages.append({"role": "system", "content": prompt["text"]})
        for item in conversation:
            messages.append(
                {
                    "role": item["role"],
                    "content": item["content"][0]["text"],
                }
            )
        return messages

    @staticmethod
    def _serialize_anthropic_invoke(
        *,
        request: CompletionRequest,
        conversation: list[dict],
        system_prompts: list[dict],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        messages = []
        for item in conversation:
            messages.append(
                {
                    "role": item["role"],
                    "content": [
                        {"type": "text", "text": item["content"][0]["text"]}
                    ],
                }
            )

        body: dict[str, Any] = {
            "anthropic_version": request.vendor_params.get(
                "anthropic_version",
                "bedrock-2023-05-31",
            ),
            "messages": messages,
        }
        if system_prompts:
            body["system"] = "\n\n".join(prompt["text"] for prompt in system_prompts)
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop_sequences"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_meta_invoke(
        *,
        prompt: str,
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt}
        if "maxTokens" in inference_config:
            body["max_gen_len"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        return body

    @staticmethod
    def _serialize_titan_text_invoke(
        *,
        prompt: str,
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        text_generation_config: dict[str, Any] = {}
        if "maxTokens" in inference_config:
            text_generation_config["maxTokenCount"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            text_generation_config["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            text_generation_config["topP"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            text_generation_config["stopSequences"] = inference_config["stopSequences"]

        body: dict[str, Any] = {"inputText": prompt}
        if text_generation_config:
            body["textGenerationConfig"] = text_generation_config
        return body

    @staticmethod
    def _serialize_nova_invoke(
        *,
        request: CompletionRequest,
        conversation: list[dict],
        system_prompts: list[dict],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schemaVersion": request.vendor_params.get(
                "nova_schema_version",
                "messages-v1",
            ),
            "messages": conversation,
        }
        if system_prompts:
            body["system"] = system_prompts
        if inference_config:
            body["inferenceConfig"] = dict(inference_config)

        additional_request_fields = request.vendor_params.get(
            "additional_model_request_fields"
        )
        if isinstance(additional_request_fields, dict) and additional_request_fields:
            body["additionalModelRequestFields"] = additional_request_fields

        tool_config = request.vendor_params.get("tool_config")
        if isinstance(tool_config, dict) and tool_config:
            body["toolConfig"] = tool_config

        top_k = request.vendor_params.get("top_k")
        if top_k is not None:
            body.setdefault("inferenceConfig", {})
            body["inferenceConfig"]["topK"] = int(top_k)

        return body

    @staticmethod
    def _serialize_ai21_jurassic_invoke(
        *,
        prompt: str,
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt}
        if "maxTokens" in inference_config:
            body["maxTokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["topP"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stopSequences"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_ai21_jamba_invoke(
        *,
        chat_messages: list[dict[str, str]],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": chat_messages,
        }
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_cohere_command_r_invoke(
        *,
        prompt: str,
        conversation: list[dict],
        system_prompts: list[dict],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        message = prompt
        chat_history: list[dict[str, str]] = []
        if conversation:
            message = conversation[-1]["content"][0]["text"]
            for item in conversation[:-1]:
                chat_history.append(
                    {
                        "role": "USER" if item["role"] == "user" else "CHATBOT",
                        "message": item["content"][0]["text"],
                    }
                )

        body: dict[str, Any] = {"message": message}
        if chat_history:
            body["chat_history"] = chat_history
        if system_prompts:
            body["preamble"] = "\n\n".join(prompt["text"] for prompt in system_prompts)
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop_sequences"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_cohere_command_invoke(
        *,
        prompt: str,
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt}
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop_sequences"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_mistral_chat_invoke(
        *,
        chat_messages: list[dict[str, str]],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"messages": chat_messages}
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_mistral_prompt_invoke(
        *,
        prompt: str,
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt}
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_deepseek_invoke(
        *,
        prompt: str,
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"prompt": prompt}
        if "maxTokens" in inference_config:
            body["max_new_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_openai_chat_invoke(
        *,
        chat_messages: list[dict[str, str]],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"messages": chat_messages}
        if "maxTokens" in inference_config:
            body["max_completion_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _serialize_writer_chat_invoke(
        *,
        chat_messages: list[dict[str, str]],
        inference_config: dict[str, Any],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"messages": chat_messages}
        if "maxTokens" in inference_config:
            body["max_tokens"] = inference_config["maxTokens"]
        if "temperature" in inference_config:
            body["temperature"] = inference_config["temperature"]
        if "topP" in inference_config:
            body["top_p"] = inference_config["topP"]
        if "stopSequences" in inference_config:
            body["stop"] = inference_config["stopSequences"]
        return body

    @staticmethod
    def _apply_invoke_extra_fields(
        request: CompletionRequest,
        body: dict[str, Any],
    ) -> None:
        extra_fields = request.vendor_params.get("invoke_extra_fields")
        if isinstance(extra_fields, dict) and extra_fields:
            body.update(extra_fields)

    @staticmethod
    def _messages_to_prompt(
        conversation: list[dict], system_prompts: list[dict]
    ) -> str:
        prompt_parts = []
        if system_prompts:
            prompt_parts.append("System:")
            prompt_parts.extend(item["text"] for item in system_prompts)

        for item in conversation:
            role = item["role"].capitalize()
            text = item["content"][0]["text"]
            prompt_parts.append(f"{role}: {text}")

        prompt_parts.append("Assistant:")
        return "\n".join(prompt_parts)

    @staticmethod
    def _merge_inference_into_custom_body(
        body: dict[str, Any],
        inference_config: dict[str, Any],
    ) -> None:
        if not inference_config:
            return

        if inference_config.get("maxTokens") is not None:
            body.setdefault("max_tokens", inference_config.get("maxTokens"))
        if inference_config.get("temperature") is not None:
            body.setdefault("temperature", inference_config.get("temperature"))
        if inference_config.get("topP") is not None:
            body.setdefault("top_p", inference_config.get("topP"))
        if inference_config.get("stopSequences") is not None:
            body.setdefault("stop", inference_config.get("stopSequences"))

    def _parse_converse_response(
        self,
        *,
        model: str,
        payload: dict[str, Any],
    ) -> CompletionResponse:
        message = payload.get("output", {}).get("message", {})
        content_blocks = message.get("content", [])
        text = "".join(
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ).strip()

        usage_data = payload.get("usage")
        usage = None
        if isinstance(usage_data, dict):
            usage = CompletionUsage(
                input_tokens=usage_data.get("inputTokens"),
                output_tokens=usage_data.get("outputTokens"),
                total_tokens=usage_data.get("totalTokens"),
            )

        vendor_fields: dict[str, Any] = {}
        if "additionalModelResponseFields" in payload:
            vendor_fields["additionalModelResponseFields"] = payload[
                "additionalModelResponseFields"
            ]

        return CompletionResponse(
            content=text,
            model=model,
            stop_reason=payload.get("stopReason"),
            usage=usage,
            vendor_fields=vendor_fields,
            raw=payload,
        )

    def _parse_invoke_model_response(
        self,
        request: CompletionRequest,
        *,
        model: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
    ) -> CompletionResponse:
        family = self._resolve_invoke_family(request, model=model)
        response_paths = request.vendor_params.get("invoke_response_paths")
        if not isinstance(response_paths, list):
            response_paths = self._default_response_paths(family)

        text = ""
        for path in response_paths:
            candidate = self._extract_path(payload, path)
            candidate_text = self._coerce_text_candidate(candidate)
            if isinstance(candidate_text, str) and candidate_text.strip():
                text = candidate_text
                break

        stop_reason = None
        stop_paths = request.vendor_params.get("invoke_stop_reason_paths")
        if not isinstance(stop_paths, list):
            stop_paths = self._default_stop_reason_paths(family)
        for path in stop_paths:
            candidate = self._extract_path(payload, path)
            candidate_text = self._coerce_text_candidate(candidate)
            if isinstance(candidate_text, str) and candidate_text.strip():
                stop_reason = candidate_text
                break

        usage = self._extract_usage(payload)

        return CompletionResponse(
            content=text.strip(),
            model=model,
            stop_reason=stop_reason,
            usage=usage,
            raw={"invoke_model_response": raw, "payload": payload},
        )

    @staticmethod
    def _extract_path(payload: dict[str, Any], path: str) -> Any:
        node: Any = payload
        for part in path.split("."):
            if isinstance(node, list):
                try:
                    node = node[int(part)]
                except (ValueError, IndexError):
                    return None
                continue

            if not isinstance(node, dict):
                return None
            if part not in node:
                return None
            node = node[part]
        return node

    @staticmethod
    def _coerce_text_candidate(candidate: Any) -> str | None:
        if isinstance(candidate, str):
            return candidate

        if isinstance(candidate, list):
            parts = []
            for item in candidate:
                text = BedrockCompletionGateway._coerce_text_candidate(item)
                if isinstance(text, str):
                    parts.append(text)
            if parts:
                return "".join(parts)
            return None

        if isinstance(candidate, dict):
            text = candidate.get("text")
            if isinstance(text, str):
                return text

            content = candidate.get("content")
            if content is not None:
                return BedrockCompletionGateway._coerce_text_candidate(content)

        return None

    @staticmethod
    def _extract_usage(payload: dict[str, Any]) -> CompletionUsage | None:
        usage_data = payload.get("usage")
        if not isinstance(usage_data, dict):
            return None

        input_tokens = usage_data.get("inputTokens")
        if input_tokens is None:
            input_tokens = usage_data.get("prompt_tokens")
        if input_tokens is None:
            input_tokens = usage_data.get("input_tokens")

        output_tokens = usage_data.get("outputTokens")
        if output_tokens is None:
            output_tokens = usage_data.get("completion_tokens")
        if output_tokens is None:
            output_tokens = usage_data.get("output_tokens")

        total_tokens = usage_data.get("totalTokens")
        if total_tokens is None:
            total_tokens = usage_data.get("total_tokens")
        if (
            total_tokens is None
            and isinstance(input_tokens, int)
            and isinstance(output_tokens, int)
        ):
            total_tokens = input_tokens + output_tokens

        if (
            input_tokens is None
            and output_tokens is None
            and total_tokens is None
        ):
            return None

        return CompletionUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _default_response_paths(family: str) -> list[str]:
        if family == "anthropic":
            return ["content.0.text"]
        if family == "meta":
            return ["generation"]
        if family == "amazon_titan_text":
            return ["results.0.outputText"]
        if family == "amazon_nova":
            return ["output.message.content"]
        if family == "ai21_jurassic":
            return ["completions.0.data.text"]
        if family == "ai21_jamba":
            return ["choices.0.message.content", "choices.0.text"]
        if family == "cohere_command_r":
            return ["text", "generations.0.text"]
        if family == "cohere_command":
            return ["generations.0.text", "text"]
        if family == "mistral_chat":
            return ["choices.0.message.content", "outputs.0.text"]
        if family == "mistral_prompt":
            return ["outputs.0.text"]
        if family == "deepseek":
            return ["choices.0.text", "choices.0.message.content"]
        if family in {"openai_chat", "writer_chat"}:
            return ["choices.0.message.content", "choices.0.text"]
        return ["outputText", "completion"]

    @staticmethod
    def _default_stop_reason_paths(family: str) -> list[str]:
        if family == "anthropic":
            return ["stop_reason"]
        if family == "meta":
            return ["stop_reason"]
        if family == "amazon_titan_text":
            return ["results.0.completionReason"]
        if family == "amazon_nova":
            return ["stopReason"]
        if family == "ai21_jurassic":
            return ["completions.0.finishReason"]
        if family == "ai21_jamba":
            return ["choices.0.finish_reason", "finish_reason"]
        if family == "cohere_command_r":
            return ["finish_reason", "generations.0.finish_reason"]
        if family == "cohere_command":
            return ["generations.0.finish_reason"]
        if family == "mistral_chat":
            return ["choices.0.finish_reason", "outputs.0.stop_reason"]
        if family == "mistral_prompt":
            return ["outputs.0.stop_reason"]
        if family == "deepseek":
            return ["choices.0.stop_reason", "choices.0.finish_reason"]
        if family in {"openai_chat", "writer_chat"}:
            return ["choices.0.finish_reason", "finish_reason"]
        return ["stopReason"]

    @staticmethod
    def _error_message_from_client_error(error: ClientError) -> str:
        data = error.response.get("Error", {})
        code = data.get("Code", "Unknown")
        message = data.get("Message", "No detail provided.")
        return f"{code}: {message}"

    @staticmethod
    def _should_fallback_to_invoke_model(error: ClientError) -> bool:
        data = error.response.get("Error", {})
        code = str(data.get("Code", "")).lower()
        message = str(data.get("Message", "")).lower()

        if code not in {"validationexception", "badrequestexception"}:
            return False

        if "converse" not in message:
            return False

        return any(
            marker in message
            for marker in [
                "not support",
                "unsupported",
                "not supported",
            ]
        )
