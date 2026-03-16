"""Provides an OpenAI completion gateway."""

import asyncio
import inspect
import json
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.message_serialization import (
    serialize_completion_message_content,
    serialize_completion_message_dict,
)
from mugen.core.gateway.completion.timeout_config import (
    parse_bool_like,
    require_fields_in_production,
    resolve_optional_positive_float,
    warn_missing_in_production,
)


# pylint: disable=too-few-public-methods
class OpenAICompletionGateway(ICompletionGateway):
    """An OpenAI completion gateway with chat and responses support."""

    _provider = "openai"
    _chat_surface = "chat_completions"
    _responses_surface = "responses"
    _surface_vendor_param = "openai_api"
    _removed_legacy_vendor_param_keys = (
        "use_legacy_max_tokens",
        "stream",
        "stream_options",
    )

    _chat_vendor_passthrough_keys = (
        "audio",
        "frequency_penalty",
        "function_call",
        "functions",
        "logit_bias",
        "logprobs",
        "metadata",
        "modalities",
        "n",
        "parallel_tool_calls",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "seed",
        "service_tier",
        "store",
        "tool_choice",
        "tools",
        "top_logprobs",
        "user",
    )
    _responses_vendor_passthrough_keys = (
        "include",
        "max_tool_calls",
        "previous_response_id",
        "prompt",
        "prompt_cache_key",
        "reasoning",
        "safety_identifier",
        "text",
        "truncation",
        "conversation",
        "metadata",
        "parallel_tool_calls",
        "service_tier",
        "store",
        "temperature",
        "top_p",
        "tool_choice",
        "tools",
        "top_logprobs",
        "user",
    )

    _chat_response_vendor_keys = (
        "id",
        "object",
        "created",
        "system_fingerprint",
        "service_tier",
    )
    _responses_response_vendor_keys = (
        "id",
        "object",
        "created_at",
        "status",
        "service_tier",
        "previous_response_id",
        "conversation",
    )

    _responses_tool_call_types = (
        "function_call",
        "custom_tool_call",
        "computer_call",
        "code_interpreter_call",
        "file_search_call",
        "web_search_call",
        "image_generation_call",
        "mcp_call",
        "mcp_list_tools",
        "mcp_approval_request",
        "local_shell_call",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway

        api_kwargs: dict[str, Any] = {
            "api_key": self._config.openai.api.key,
        }
        base_url = getattr(self._config.openai.api, "base_url", None)
        if isinstance(base_url, str) and base_url.strip():
            api_kwargs["base_url"] = base_url.strip()

        self._timeout_seconds = self._resolve_timeout_seconds()
        require_fields_in_production(
            config=self._config,
            provider_label="OpenAICompletionGateway",
            field_values={"timeout_seconds": self._timeout_seconds},
        )
        if self._timeout_seconds is not None:
            api_kwargs["timeout"] = self._timeout_seconds

        self._api = AsyncOpenAI(**api_kwargs)
        self._warn_missing_timeout_in_production()

    def _resolve_timeout_seconds(self) -> float | None:
        return resolve_optional_positive_float(
            value=getattr(self._config.openai.api, "timeout_seconds", None),
            field_name="timeout_seconds",
            provider_label="OpenAICompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _warn_missing_timeout_in_production(self) -> None:
        warn_missing_in_production(
            config=self._config,
            provider_label="OpenAICompletionGateway",
            logging_gateway=self._logging_gateway,
            field_values={"timeout_seconds": self._timeout_seconds},
        )

    async def check_readiness(self) -> None:
        _ = self._api
        self._resolve_operation_config("classification")
        self._resolve_operation_config("completion")
        models_api = getattr(self._api, "models", None)
        list_models = getattr(models_api, "list", None)
        if callable(list_models) is not True:
            raise RuntimeError(
                "OpenAI completion gateway readiness probe unavailable: models.list."
            )
        timeout_seconds = self._timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0
        try:
            try:
                readiness_probe = list_models(limit=1)
            except TypeError:
                # openai-python >= 1.0 accepts list() without limit.
                readiness_probe = list_models()
            await asyncio.wait_for(
                readiness_probe,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError(
                "OpenAI completion gateway readiness probe failed."
            ) from exc

    async def aclose(self) -> None:
        close = getattr(self._api, "close", None)
        if callable(close) is not True:
            return None
        maybe_awaitable = close()
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
        return None

    async def get_completion(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        completion_request = request
        self._validate_removed_legacy_vendor_params(completion_request)
        operation_config = self._resolve_operation_config(completion_request.operation)

        try:
            surface = self._resolve_openai_surface(
                completion_request,
                operation_config,
            )

            if surface == self._responses_surface:
                model, kwargs = self._serialize_responses_kwargs(
                    completion_request,
                    operation_config,
                )
                response_or_stream = await self._api.responses.create(**kwargs)
                if kwargs["stream"]:
                    return await self._parse_responses_stream_response(
                        stream=response_or_stream,
                        model=model,
                        operation=completion_request.operation,
                    )

                return self._parse_responses_standard_response(
                    response=response_or_stream,
                    model=model,
                    operation=completion_request.operation,
                )

            model, kwargs = self._serialize_chat_kwargs(
                completion_request,
                operation_config,
            )
            chat_completion = await self._api.chat.completions.create(**kwargs)
            if kwargs["stream"]:
                return await self._parse_chat_stream_response(
                    stream=chat_completion,
                    model=model,
                    operation=completion_request.operation,
                )

            return self._parse_chat_standard_response(
                chat_completion=chat_completion,
                model=model,
                operation=completion_request.operation,
            )
        except OpenAIError as e:
            self._logging_gateway.warning(
                "OpenAICompletionGateway.get_completion: "
                "An error was encountered while trying the OpenAI API."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=str(e),
                cause=e,
                timeout_applied=self._timeout_seconds,
            ) from e
        except CompletionGatewayError:
            raise
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "OpenAICompletionGateway.get_completion: "
                "Unexpected failure while processing completion request."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Unexpected OpenAI completion failure.",
                cause=e,
                timeout_applied=self._timeout_seconds,
            ) from e

    def _serialize_chat_kwargs(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = request.model or operation_config["model"]

        temperature = self._resolve_temperature(request, operation_config=operation_config)
        top_p = self._resolve_top_p(request, operation_config=operation_config)

        stream = self._resolve_stream(request)

        kwargs: dict[str, Any] = {
            "messages": [
                serialize_completion_message_dict(message)
                for message in request.messages
            ],
            "model": model,
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if request.inference.stop:
            kwargs["stop"] = request.inference.stop

        stream_options = self._resolve_stream_options(request)
        if stream and stream_options is not None:
            kwargs["stream_options"] = stream_options

        max_tokens = self._resolve_chat_max_tokens(
            request,
            operation_config=operation_config,
        )
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = int(max_tokens)

        for key in self._chat_vendor_passthrough_keys:
            if key in request.vendor_params:
                kwargs[key] = request.vendor_params[key]

        return model, kwargs

    def _serialize_responses_kwargs(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = request.model or operation_config["model"]

        stream = self._resolve_stream(request)
        stream_options = self._resolve_stream_options(request)

        instructions, input_items = self._serialize_responses_input(request)

        kwargs: dict[str, Any] = {
            "model": model,
            "stream": stream,
        }
        if instructions:
            kwargs["instructions"] = instructions
        if input_items:
            kwargs["input"] = input_items
        elif not instructions:
            kwargs["input"] = []

        temperature = self._resolve_temperature(request, operation_config=operation_config)
        if temperature is not None:
            kwargs["temperature"] = temperature

        top_p = self._resolve_top_p(request, operation_config=operation_config)
        if top_p is not None:
            kwargs["top_p"] = top_p

        max_tokens = self._resolve_responses_max_tokens(
            request,
            operation_config=operation_config,
        )
        if max_tokens is not None:
            kwargs["max_output_tokens"] = int(max_tokens)

        if stream and stream_options is not None:
            kwargs["stream_options"] = stream_options

        for key in self._responses_vendor_passthrough_keys:
            if key not in request.vendor_params:
                continue
            if key in {"temperature", "top_p"}:
                kwargs.setdefault(key, request.vendor_params[key])
                continue
            kwargs[key] = request.vendor_params[key]

        return model, kwargs

    async def _parse_chat_stream_response(
        self,
        *,
        stream: Any,
        model: str,
        operation: str,
    ) -> CompletionResponse:
        content_parts: list[str] = []
        rich_content_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        stop_reason = None
        usage = None
        raw_chunks = []
        metadata: dict[str, Any] = {}

        async for chunk in stream:
            raw_chunks.append(chunk)

            chunk_payload = self._normalize_dict(chunk)
            for key in self._chat_response_vendor_keys:
                if key in chunk_payload:
                    metadata[key] = chunk_payload[key]

            choices = getattr(chunk, "choices", []) or []
            if choices:
                choice = choices[0]
                if getattr(choice, "finish_reason", None) is not None:
                    stop_reason = choice.finish_reason

                delta = getattr(choice, "delta", None)
                delta_content = getattr(delta, "content", None)
                if isinstance(delta_content, str):
                    content_parts.append(delta_content)
                elif delta_content is not None:
                    normalized_content = self._normalize_content(delta_content)
                    if isinstance(normalized_content, dict):
                        rich_content_parts.append(normalized_content)
                    elif isinstance(normalized_content, list):
                        rich_content_parts.extend(normalized_content)

                delta_tool_calls = getattr(delta, "tool_calls", None)
                if isinstance(delta_tool_calls, list):
                    for delta_tool_call in delta_tool_calls:
                        normalized_tool_call = self._normalize_dict(delta_tool_call)
                        if normalized_tool_call:
                            tool_calls.append(normalized_tool_call)

            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = self._usage_from_payload(chunk_usage)

        if not raw_chunks:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message="OpenAI stream produced no response chunks.",
            )

        content: Any = "".join(content_parts)
        if not content and rich_content_parts:
            content = rich_content_parts

        vendor_fields = metadata
        if rich_content_parts:
            vendor_fields["stream_content_deltas"] = rich_content_parts

        return CompletionResponse(
            content=content,
            model=model,
            stop_reason=stop_reason,
            tool_calls=tool_calls,
            usage=usage,
            vendor_fields=vendor_fields,
            raw=raw_chunks,
        )

    def _parse_chat_standard_response(
        self,
        *,
        chat_completion: Any,
        model: str,
        operation: str,
    ) -> CompletionResponse:
        choices = getattr(chat_completion, "choices", None)
        if not isinstance(choices, list) or not choices:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message="OpenAI response did not include any completion choices.",
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        usage = self._usage_from_payload(getattr(chat_completion, "usage", None))
        message_payload = self._normalize_dict(message)
        content = self._normalize_content(getattr(message, "content", None))
        tool_calls = self._normalize_list_of_dicts(getattr(message, "tool_calls", None))

        response_vendor_fields: dict[str, Any] = {}
        response_payload = self._normalize_dict(chat_completion)
        if response_payload:
            for key in self._chat_response_vendor_keys:
                if key in response_payload:
                    response_vendor_fields[key] = response_payload[key]

        if len(choices) > 1:
            response_vendor_fields["additional_choices"] = [
                self._normalize_dict(extra_choice) for extra_choice in choices[1:]
            ]

        return CompletionResponse(
            content=content,
            model=getattr(chat_completion, "model", model),
            stop_reason=getattr(choice, "finish_reason", None),
            message=message_payload,
            tool_calls=tool_calls,
            usage=usage,
            vendor_fields=response_vendor_fields,
            raw=chat_completion,
        )

    async def _parse_responses_stream_response(
        self,
        *,
        stream: Any,
        model: str,
        operation: str,
    ) -> CompletionResponse:
        raw_events: list[Any] = []
        output_text_deltas: list[str] = []
        output_items: list[dict[str, Any]] = []
        tool_call_arguments_by_item_id: dict[str, str] = {}
        terminal_response: Any = None

        async for event in stream:
            raw_events.append(event)

            event_payload = self._normalize_dict(event)
            event_type = event_payload.get("type")

            if event_type == "error":
                error_message = event_payload.get("message")
                message = (
                    error_message
                    if isinstance(error_message, str) and error_message
                    else "OpenAI Responses stream returned an error event."
                )
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=operation,
                    message=message,
                )

            if event_type == "response.failed":
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=operation,
                    message=self._extract_responses_terminal_error_message(
                        event_payload.get("response"),
                        fallback="OpenAI Responses stream failed.",
                    ),
                )

            if event_type == "response.incomplete":
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=operation,
                    message=self._extract_responses_terminal_error_message(
                        event_payload.get("response"),
                        fallback="OpenAI Responses stream ended incompletely.",
                    ),
                )

            if event_type == "response.completed":
                terminal_response = event_payload.get("response")
                continue

            if event_type == "response.output_text.delta":
                delta = event_payload.get("delta")
                if isinstance(delta, str):
                    output_text_deltas.append(delta)
                continue

            if event_type in {
                "response.output_item.added",
                "response.output_item.done",
            }:
                item_payload = self._normalize_dict(event_payload.get("item"))
                if item_payload:
                    output_items.append(item_payload)
                continue

            if event_type == "response.function_call_arguments.delta":
                item_id = event_payload.get("item_id")
                delta = event_payload.get("delta")
                if isinstance(item_id, str) and isinstance(delta, str):
                    tool_call_arguments_by_item_id[item_id] = (
                        tool_call_arguments_by_item_id.get(item_id, "") + delta
                    )
                continue

            if event_type == "response.function_call_arguments.done":
                item_id = event_payload.get("item_id")
                arguments = event_payload.get("arguments")
                if isinstance(item_id, str) and isinstance(arguments, str):
                    tool_call_arguments_by_item_id[item_id] = arguments

        if not raw_events:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message="OpenAI Responses stream produced no events.",
            )

        if terminal_response is None:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=(
                    "OpenAI Responses stream did not emit a terminal completed "
                    "response payload."
                ),
            )

        parsed_response = self._parse_responses_standard_response(
            response=terminal_response,
            model=model,
            operation=operation,
        )

        stream_tool_calls = self._extract_responses_tool_calls(output_items)
        merged_tool_calls = self._merge_responses_tool_calls(
            parsed_tool_calls=parsed_response.tool_calls,
            stream_tool_calls=stream_tool_calls,
            stream_tool_call_arguments=tool_call_arguments_by_item_id,
        )

        content = parsed_response.content
        if (content is None or content == "") and output_text_deltas:
            content = "".join(output_text_deltas)

        vendor_fields = dict(parsed_response.vendor_fields)
        if output_text_deltas:
            vendor_fields["stream_text_deltas"] = "".join(output_text_deltas)
        if output_items:
            vendor_fields["stream_output_items"] = output_items
        if tool_call_arguments_by_item_id:
            vendor_fields["stream_tool_call_arguments"] = tool_call_arguments_by_item_id

        return CompletionResponse(
            content=content,
            model=parsed_response.model,
            stop_reason=parsed_response.stop_reason,
            message=parsed_response.message,
            tool_calls=merged_tool_calls,
            usage=parsed_response.usage,
            vendor_fields=vendor_fields,
            raw=raw_events,
        )

    def _parse_responses_standard_response(
        self,
        *,
        response: Any,
        model: str,
        operation: str,
    ) -> CompletionResponse:
        response_payload = self._normalize_dict(response)
        output_items = self._normalize_list_of_dicts(response_payload.get("output"))

        message_payload, content, structured_content_blocks = self._extract_responses_content(
            output_items
        )
        tool_calls = self._extract_responses_tool_calls(output_items)

        if content is None:
            content = self._extract_responses_output_text(response, response_payload)

        usage = self._usage_from_payload(response_payload.get("usage"))

        vendor_fields: dict[str, Any] = {}
        for key in self._responses_response_vendor_keys:
            if key in response_payload:
                vendor_fields[key] = response_payload[key]

        if "error" in response_payload:
            vendor_fields["error"] = response_payload["error"]
        if "incomplete_details" in response_payload:
            vendor_fields["incomplete_details"] = response_payload["incomplete_details"]
        if structured_content_blocks:
            vendor_fields["structured_content_blocks"] = structured_content_blocks

        return CompletionResponse(
            content=content,
            model=response_payload.get("model", model),
            stop_reason=self._extract_responses_stop_reason(response_payload),
            message=message_payload,
            tool_calls=tool_calls,
            usage=usage,
            vendor_fields=vendor_fields,
            raw=response,
        )

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._config.openai.api.dict[operation]
        except (AttributeError, KeyError) as e:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing OpenAI operation configuration: {operation}",
                cause=e,
            ) from e

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid OpenAI operation configuration: {operation}",
            )

        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"OpenAI operation '{operation}' is missing model.",
            )
        if "max_tokens" in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=(
                    f"OpenAI operation '{operation}' includes removed legacy key "
                    "'max_tokens'. Use 'max_completion_tokens'."
                ),
            )

        return cfg

    def _resolve_openai_surface(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> str:
        raw_surface = request.vendor_params.get(
            self._surface_vendor_param,
            operation_config.get("surface", self._chat_surface),
        )

        if not isinstance(raw_surface, str):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=(
                    "Invalid OpenAI API surface value. Expected one of "
                    "'chat_completions' or 'responses'."
                ),
            )

        normalized_surface = raw_surface.strip().lower().replace("-", "_")
        if normalized_surface in {self._chat_surface, self._responses_surface}:
            return normalized_surface

        raise CompletionGatewayError(
            provider=self._provider,
            operation=request.operation,
            message=(
                "Invalid OpenAI API surface value. Expected one of "
                "'chat_completions' or 'responses'."
            ),
        )

    @staticmethod
    def _resolve_temperature(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> float | None:
        temperature = request.inference.temperature
        if temperature is None and "temp" in operation_config:
            temperature = float(operation_config["temp"])
        return temperature

    @staticmethod
    def _resolve_top_p(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> float | None:
        top_p = request.inference.top_p
        if top_p is None and "top_p" in operation_config:
            top_p = float(operation_config["top_p"])
        return top_p

    def _resolve_stream(self, request: CompletionRequest) -> bool:
        return self._parse_bool_like(
            request=request,
            value=request.inference.stream,
            field_name="inference.stream",
        )

    def _parse_bool_like(
        self,
        *,
        request: CompletionRequest,
        value: Any,
        field_name: str,
    ) -> bool:
        try:
            return parse_bool_like(
                value=value,
                field_name=field_name,
                provider_label="OpenAICompletionGateway",
            )
        except ValueError as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=str(exc),
                cause=exc,
                timeout_applied=self._timeout_seconds,
            ) from exc

    @staticmethod
    def _resolve_stream_options(request: CompletionRequest) -> dict[str, Any] | None:
        stream_options = request.inference.stream_options
        if isinstance(stream_options, dict) and stream_options:
            return stream_options

        return None

    @staticmethod
    def _resolve_chat_max_tokens(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> int | None:
        max_tokens = request.inference.max_completion_tokens
        if max_tokens is None and "max_completion_tokens" in operation_config:
            max_tokens = int(operation_config["max_completion_tokens"])
        return max_tokens

    @staticmethod
    def _resolve_responses_max_tokens(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> int | None:
        max_tokens = request.inference.max_completion_tokens
        if max_tokens is None and "max_output_tokens" in operation_config:
            max_tokens = int(operation_config["max_output_tokens"])
        if max_tokens is None and "max_completion_tokens" in operation_config:
            max_tokens = int(operation_config["max_completion_tokens"])
        return max_tokens

    def _validate_removed_legacy_vendor_params(
        self,
        request: CompletionRequest,
    ) -> None:
        for key in self._removed_legacy_vendor_param_keys:
            if key not in request.vendor_params:
                continue
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=(
                    "OpenAICompletionGateway: Removed legacy vendor param "
                    f"'{key}' is not supported."
                ),
                timeout_applied=self._timeout_seconds,
            )

    @classmethod
    def _serialize_responses_input(
        cls,
        request: CompletionRequest,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        instructions_parts: list[str] = []
        input_items: list[dict[str, Any]] = []

        for message in request.messages:
            if message.role == "system":
                system_content = cls._serialize_instruction_content(message.content)
                if system_content:
                    instructions_parts.append(system_content)
                continue

            input_items.append(serialize_completion_message_dict(message))

        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, input_items

    @staticmethod
    def _serialize_instruction_content(value: Any) -> str:
        return serialize_completion_message_content(value)

    @classmethod
    def _extract_responses_content(
        cls,
        output_items: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, Any, list[dict[str, Any]]]:
        assistant_messages = [
            item
            for item in output_items
            if item.get("type") == "message" and item.get("role") == "assistant"
        ]

        message_payload = assistant_messages[0] if assistant_messages else None

        content_blocks: list[dict[str, Any]] = []
        text_parts: list[str] = []
        structured_content_blocks: list[dict[str, Any]] = []
        for message in assistant_messages:
            normalized_message_content = cls._normalize_content(message.get("content"))
            if isinstance(normalized_message_content, dict):
                content_blocks.append(normalized_message_content)
            elif isinstance(normalized_message_content, list):
                content_blocks.extend(normalized_message_content)

        for content_block in content_blocks:
            if (
                content_block.get("type") == "output_text"
                and isinstance(content_block.get("text"), str)
            ):
                text_parts.append(content_block["text"])
            else:
                structured_content_blocks.append(content_block)

        content: Any = None
        if text_parts:
            content = "".join(text_parts)
        elif content_blocks:
            content = content_blocks

        return message_payload, content, structured_content_blocks

    @classmethod
    def _extract_responses_output_text(
        cls,
        response: Any,
        response_payload: dict[str, Any],
    ) -> str | None:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text

        payload_output_text = response_payload.get("output_text")
        if isinstance(payload_output_text, str):
            return payload_output_text

        text_field = response_payload.get("text")
        text_payload = cls._normalize_dict(text_field)
        text_value = text_payload.get("value")
        if isinstance(text_value, str):
            return text_value

        return None

    @classmethod
    def _extract_responses_tool_calls(
        cls,
        output_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []

        for item in output_items:
            item_type = item.get("type")
            if cls._is_responses_tool_call_item(item_type):
                tool_calls.append(item)

        return tool_calls

    @classmethod
    def _merge_responses_tool_calls(
        cls,
        *,
        parsed_tool_calls: list[dict[str, Any]],
        stream_tool_calls: list[dict[str, Any]],
        stream_tool_call_arguments: dict[str, str],
    ) -> list[dict[str, Any]]:
        merged_tool_calls: list[dict[str, Any]] = [dict(item) for item in parsed_tool_calls]

        seen_item_ids: set[str] = set()
        for tool_call in merged_tool_calls:
            item_id = tool_call.get("id")
            if isinstance(item_id, str):
                seen_item_ids.add(item_id)

        for stream_tool_call in stream_tool_calls:
            item_id = stream_tool_call.get("id")
            if isinstance(item_id, str) and item_id in seen_item_ids:
                continue

            merged_tool_calls.append(dict(stream_tool_call))
            if isinstance(item_id, str):
                seen_item_ids.add(item_id)

        for tool_call in merged_tool_calls:
            item_id = tool_call.get("id")
            if not isinstance(item_id, str):
                continue
            if item_id not in stream_tool_call_arguments:
                continue
            if "arguments" in tool_call and tool_call["arguments"]:
                continue

            tool_call["arguments"] = stream_tool_call_arguments[item_id]

        for item_id, arguments in stream_tool_call_arguments.items():
            if item_id in seen_item_ids:
                continue
            merged_tool_calls.append(
                {
                    "id": item_id,
                    "type": "function_call",
                    "arguments": arguments,
                }
            )

        return merged_tool_calls

    @classmethod
    def _extract_responses_stop_reason(
        cls,
        response_payload: dict[str, Any],
    ) -> str | None:
        status = response_payload.get("status")
        if status == "incomplete":
            incomplete_details = cls._normalize_dict(
                response_payload.get("incomplete_details")
            )
            reason = incomplete_details.get("reason")
            if isinstance(reason, str):
                return reason

        if isinstance(status, str):
            return status

        return None

    @classmethod
    def _extract_responses_terminal_error_message(
        cls,
        response: Any,
        *,
        fallback: str,
    ) -> str:
        response_payload = cls._normalize_dict(response)
        error_payload = cls._normalize_dict(response_payload.get("error"))

        error_message = error_payload.get("message")
        if isinstance(error_message, str) and error_message:
            return error_message

        incomplete_details = cls._normalize_dict(response_payload.get("incomplete_details"))
        reason = incomplete_details.get("reason")
        if isinstance(reason, str) and reason:
            return f"{fallback} ({reason})"

        return fallback

    @classmethod
    def _is_responses_tool_call_item(cls, value: Any) -> bool:
        if not isinstance(value, str):
            return False

        if value in cls._responses_tool_call_types:
            return True

        return value.endswith("_call") or value.endswith("_tool_call")

    @classmethod
    def _usage_from_payload(cls, usage: Any) -> CompletionUsage | None:
        if usage is None:
            return None

        usage_payload = cls._normalize_dict(usage)
        if not usage_payload:
            return None

        input_tokens = usage_payload.get("prompt_tokens")
        if input_tokens is None:
            input_tokens = usage_payload.get("input_tokens")

        output_tokens = usage_payload.get("completion_tokens")
        if output_tokens is None:
            output_tokens = usage_payload.get("output_tokens")

        total_tokens = usage_payload.get("total_tokens")
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return None

        usage_vendor_fields: dict[str, Any] = {}
        token_keys = {
            "prompt_tokens",
            "completion_tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }
        for key, value in usage_payload.items():
            if key not in token_keys:
                usage_vendor_fields[key] = value

        return CompletionUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            vendor_fields=usage_vendor_fields,
        )

    @staticmethod
    def _normalize_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dumped

        if hasattr(value, "__dict__"):
            return {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_")
            }

        return {}

    @classmethod
    def _normalize_content(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, dict)):
            return value

        if isinstance(value, list):
            normalized: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    normalized.append(item)
                    continue

                item_payload = cls._normalize_dict(item)
                if item_payload:
                    normalized.append(item_payload)
            return normalized

        as_payload = cls._normalize_dict(value)
        if as_payload:
            return as_payload

        return None

    @classmethod
    def _normalize_list_of_dicts(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in value:
            item_payload = cls._normalize_dict(item)
            if item_payload:
                normalized.append(item_payload)

        return normalized
