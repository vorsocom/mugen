"""Provides a Groq chat completion gateway."""

# https://console.groq.com/docs/api-reference#chat

from types import SimpleNamespace
from typing import Any

from groq import AsyncGroq, GroqError

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
class GroqCompletionGateway(ICompletionGateway):
    """A Groq chat completion gateway."""

    _env_prefix = "groq"
    _provider = "groq"
    _legacy_max_tokens_vendor_flag = "use_legacy_max_tokens"
    _vendor_passthrough_keys = (
        "citation_options",
        "compound_custom",
        "disable_tool_validation",
        "documents",
        "exclude_domains",
        "frequency_penalty",
        "function_call",
        "functions",
        "include_domains",
        "include_reasoning",
        "logit_bias",
        "logprobs",
        "metadata",
        "n",
        "parallel_tool_calls",
        "presence_penalty",
        "reasoning_effort",
        "reasoning_format",
        "response_format",
        "search_settings",
        "seed",
        "service_tier",
        "store",
        "tool_choice",
        "tools",
        "top_logprobs",
        "user",
        "verbosity",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway
        timeout_seconds = self._resolve_timeout_seconds()
        self._timeout_seconds = timeout_seconds
        client_kwargs: dict[str, Any] = {
            "api_key": self._config.groq.api.key,
        }
        if timeout_seconds is not None:
            client_kwargs["timeout"] = timeout_seconds
        self._api = AsyncGroq(**client_kwargs)
        self._warn_missing_timeout_in_production()

    def _resolve_timeout_seconds(self) -> float | None:
        timeout_seconds = getattr(self._config.groq.api, "timeout_seconds", None)
        if timeout_seconds is None:
            return None
        try:
            resolved = float(timeout_seconds)
        except (TypeError, ValueError):
            self._logging_gateway.warning(
                "GroqCompletionGateway: Invalid timeout_seconds configuration."
            )
            return None
        if resolved <= 0:
            self._logging_gateway.warning(
                "GroqCompletionGateway: timeout_seconds must be positive when provided."
            )
            return None
        return resolved

    def _warn_missing_timeout_in_production(self) -> None:
        environment = str(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "environment", "")
        ).strip().lower()
        if environment == "production" and self._timeout_seconds is None:
            self._logging_gateway.warning(
                "GroqCompletionGateway: timeout_seconds is not configured in production."
            )

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
                )

            return self._parse_standard_response(
                chat_completion=chat_completion,
                model=model,
            )
        except GroqError as e:
            self._logging_gateway.warning(
                "GroqCompletionGateway.get_completion: "
                "An error was encountered while trying the Groq API."
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
                "GroqCompletionGateway.get_completion: "
                "Unexpected failure while processing completion request."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Unexpected Groq completion failure.",
                cause=e,
                timeout_applied=self._timeout_seconds,
            ) from e

    def _serialize_create_kwargs(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        model = request.model or operation_config["model"]
        temperature = request.inference.temperature
        if temperature is None:
            temperature = float(operation_config.get("temp", 0.0))

        top_p = request.inference.top_p
        if top_p is None:
            top_p = float(operation_config.get("top_p", 1.0))

        stream = request.inference.stream
        if "stream" in request.vendor_params:
            stream = bool(request.vendor_params["stream"])

        kwargs: dict[str, Any] = {
            "messages": [message.to_dict() for message in request.messages],
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            "stream": bool(stream),
        }

        stream_options = request.inference.stream_options
        if not stream_options and "stream_options" in request.vendor_params:
            stream_options = request.vendor_params["stream_options"]
        if kwargs["stream"] and isinstance(stream_options, dict) and stream_options:
            kwargs["stream_options"] = stream_options

        if request.inference.stop:
            kwargs["stop"] = request.inference.stop
        max_tokens = request.inference.effective_max_tokens
        if max_tokens is not None:
            if bool(request.vendor_params.get(self._legacy_max_tokens_vendor_flag)):
                kwargs["max_tokens"] = int(max_tokens)
            else:
                kwargs["max_completion_tokens"] = int(max_tokens)

        for key in self._vendor_passthrough_keys:
            if key in request.vendor_params:
                kwargs[key] = request.vendor_params[key]

        return model, kwargs

    async def _parse_stream_response(
        self,
        *,
        stream: Any,
        model: str,
    ) -> CompletionResponse:
        content_parts: list[str] = []
        rich_content_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        stop_reason = None
        usage = None
        raw_chunks = []

        async for chunk in stream:
            raw_chunks.append(chunk)
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
                usage = self._usage_from_response(SimpleNamespace(usage=chunk_usage))

        content: Any = "".join(content_parts)
        if not content and rich_content_parts:
            content = rich_content_parts

        vendor_fields: dict[str, Any] = {}
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

    def _parse_standard_response(
        self,
        *,
        chat_completion: Any,
        model: str,
    ) -> CompletionResponse:
        choices = getattr(chat_completion, "choices", None)
        if not isinstance(choices, list) or not choices:
            raise CompletionGatewayError(
                provider=self._provider,
                operation="completion",
                message="Groq response did not include any completion choices.",
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
            for key in ("id", "object", "created", "system_fingerprint", "x_groq"):
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

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._config.groq.api.dict[operation]
        except (AttributeError, KeyError) as e:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing Groq operation configuration: {operation}",
                cause=e,
            ) from e

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid Groq operation configuration: {operation}",
            )

        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Groq operation '{operation}' is missing model.",
            )

        return cfg

    @staticmethod
    def _usage_from_response(chat_completion: Any) -> CompletionUsage | None:
        usage = getattr(chat_completion, "usage", None)
        if usage is None:
            return None

        usage_payload = GroqCompletionGateway._normalize_dict(usage)
        usage_vendor_fields: dict[str, Any] = {}
        for key, value in usage_payload.items():
            if key not in {"prompt_tokens", "completion_tokens", "total_tokens"}:
                usage_vendor_fields[key] = value

        return CompletionUsage(
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
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
