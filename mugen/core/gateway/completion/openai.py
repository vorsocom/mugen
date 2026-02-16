"""Provides an OpenAI chat completion gateway."""

from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI, OpenAIError

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
    normalise_completion_request,
)
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class OpenAICompletionGateway(ICompletionGateway):
    """An OpenAI chat completion gateway."""

    _provider = "openai"
    _legacy_max_tokens_vendor_flag = "use_legacy_max_tokens"
    _vendor_passthrough_keys = (
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
    _response_vendor_keys = (
        "id",
        "object",
        "created",
        "system_fingerprint",
        "service_tier",
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

        timeout_seconds = getattr(self._config.openai.api, "timeout_seconds", None)
        if timeout_seconds is not None:
            api_kwargs["timeout"] = float(timeout_seconds)

        self._api = AsyncOpenAI(**api_kwargs)

    async def get_completion(
        self,
        request: CompletionRequest | list[dict[str, Any]],
        operation: str = "completion",
    ) -> CompletionResponse:
        completion_request = normalise_completion_request(request, operation=operation)
        operation_config = self._resolve_operation_config(completion_request.operation)
        model, kwargs = self._serialize_create_kwargs(
            completion_request,
            operation_config,
        )

        try:
            chat_completion = await self._api.chat.completions.create(**kwargs)
            if kwargs["stream"]:
                return await self._parse_stream_response(
                    stream=chat_completion,
                    model=model,
                    operation=completion_request.operation,
                )

            return self._parse_standard_response(
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
            ) from e

    def _serialize_create_kwargs(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = request.model or operation_config["model"]

        temperature = request.inference.temperature
        if temperature is None and "temp" in operation_config:
            temperature = float(operation_config["temp"])

        top_p = request.inference.top_p
        if top_p is None and "top_p" in operation_config:
            top_p = float(operation_config["top_p"])

        stream = bool(request.inference.stream)
        if "stream" in request.vendor_params:
            stream = bool(request.vendor_params["stream"])

        kwargs: dict[str, Any] = {
            "messages": [message.to_dict() for message in request.messages],
            "model": model,
            "stream": stream,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if request.inference.stop:
            kwargs["stop"] = request.inference.stop

        stream_options = request.inference.stream_options
        if not stream_options and "stream_options" in request.vendor_params:
            stream_options = request.vendor_params["stream_options"]
        if stream and isinstance(stream_options, dict) and stream_options:
            kwargs["stream_options"] = stream_options

        max_tokens = request.inference.effective_max_tokens
        if max_tokens is None and "max_completion_tokens" in operation_config:
            max_tokens = int(operation_config["max_completion_tokens"])
        if max_tokens is None and "max_tokens" in operation_config:
            max_tokens = int(operation_config["max_tokens"])
        if max_tokens is not None:
            if bool(request.vendor_params.get(self._legacy_max_tokens_vendor_flag)):
                kwargs["max_tokens"] = int(max_tokens)
            else:
                kwargs["max_completion_tokens"] = int(max_tokens)

        for key in self._vendor_passthrough_keys:
            if key in request.vendor_params:
                kwargs[key] = request.vendor_params[key]

        return model, kwargs

    def _parse_standard_response(
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
        usage = self._usage_from_response(chat_completion)
        message_payload = self._normalize_dict(message)
        content = self._normalize_content(getattr(message, "content", None))
        tool_calls = self._normalize_list_of_dicts(getattr(message, "tool_calls", None))

        response_vendor_fields: dict[str, Any] = {}
        response_payload = self._normalize_dict(chat_completion)
        if response_payload:
            for key in self._response_vendor_keys:
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

    async def _parse_stream_response(
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
            for key in self._response_vendor_keys:
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

        return cfg

    @classmethod
    def _usage_from_response(cls, chat_completion: Any) -> CompletionUsage | None:
        return cls._usage_from_payload(getattr(chat_completion, "usage", None))

    @classmethod
    def _usage_from_payload(cls, usage: Any) -> CompletionUsage | None:
        if usage is None:
            return None

        usage_payload = cls._normalize_dict(usage)
        usage_vendor_fields: dict[str, Any] = {}
        for key, value in usage_payload.items():
            if key not in {"prompt_tokens", "completion_tokens", "total_tokens"}:
                usage_vendor_fields[key] = value

        input_tokens = usage_payload.get("prompt_tokens")
        output_tokens = usage_payload.get("completion_tokens")
        total_tokens = usage_payload.get("total_tokens")
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return None

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
