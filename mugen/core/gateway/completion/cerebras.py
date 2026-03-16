"""Provides a Cerebras chat completion gateway."""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

from cerebras.cloud.sdk import APIError, AsyncCerebras

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.message_serialization import (
    serialize_completion_message_dict,
)
from mugen.core.gateway.completion.timeout_config import (
    parse_bool_like,
    require_fields_in_production,
    resolve_optional_positive_float,
    warn_missing_in_production,
)


# pylint: disable=too-few-public-methods
class CerebrasCompletionGateway(ICompletionGateway):
    """A Cerebras chat completion gateway."""

    _provider = "cerebras"
    _default_base_url = "https://api.cerebras.ai/v1"
    _chat_surface = "chat_completions"
    _surface_vendor_param = "cerebras_api"
    _removed_legacy_vendor_param_keys = (
        "use_legacy_max_tokens",
        "stream",
        "stream_options",
    )
    _vendor_passthrough_keys = (
        "clear_thinking",
        "logprobs",
        "n",
        "parallel_tool_calls",
        "prediction",
        "reasoning_effort",
        "response_format",
        "seed",
        "service_tier",
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
        "time_info",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway

        api_cfg = self._resolve_api_config()
        api_key = self._require_non_empty_string(api_cfg, "key")
        base_url = self._resolve_base_url(api_cfg)
        self._timeout_seconds = self._resolve_timeout_seconds(api_cfg)
        require_fields_in_production(
            config=self._config,
            provider_label="CerebrasCompletionGateway",
            field_values={"timeout_seconds": self._timeout_seconds},
        )
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
        }
        if self._timeout_seconds is not None:
            client_kwargs["timeout"] = self._timeout_seconds
        self._api = AsyncCerebras(**client_kwargs)
        self._warn_missing_timeout_in_production()

    def _resolve_api_config(self) -> Any:
        api_cfg = getattr(
            getattr(self._config, "cerebras", SimpleNamespace()),
            "api",
            None,
        )
        if api_cfg is None:
            raise RuntimeError(
                "Invalid configuration: cerebras.api section is required."
            )
        return api_cfg

    @staticmethod
    def _require_non_empty_string(api_cfg: Any, key: str) -> str:
        raw_value = getattr(api_cfg, key, None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                f"Invalid configuration: cerebras.api.{key} is required."
            )
        return raw_value.strip()

    @staticmethod
    def _resolve_base_url(api_cfg: Any) -> str:
        raw_value = getattr(api_cfg, "base_url", None)
        if not isinstance(raw_value, str):
            return CerebrasCompletionGateway._default_base_url
        normalized = raw_value.strip()
        if normalized == "":
            return CerebrasCompletionGateway._default_base_url
        return normalized

    def _resolve_timeout_seconds(self, api_cfg: Any) -> float | None:
        return resolve_optional_positive_float(
            value=getattr(api_cfg, "timeout_seconds", None),
            field_name="timeout_seconds",
            provider_label="CerebrasCompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _warn_missing_timeout_in_production(self) -> None:
        warn_missing_in_production(
            config=self._config,
            provider_label="CerebrasCompletionGateway",
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
                "Cerebras completion gateway readiness probe unavailable: models.list."
            )
        timeout_seconds = self._timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 5.0
        try:
            try:
                readiness_probe = list_models(limit=1)
            except TypeError:
                readiness_probe = list_models()
            await asyncio.wait_for(
                readiness_probe,
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError("Cerebras completion gateway readiness probe failed.") from exc

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
        self._validate_surface_aliases(completion_request, operation_config)
        self._validate_stream_options(completion_request)
        model, kwargs = self._serialize_create_kwargs(
            completion_request,
            operation_config,
        )

        try:
            chat_completion_or_stream = await self._api.chat.completions.create(**kwargs)
            if kwargs["stream"]:
                return await self._parse_stream_response(
                    stream=chat_completion_or_stream,
                    model=model,
                    operation=completion_request.operation,
                )
            return self._parse_standard_response(
                chat_completion=chat_completion_or_stream,
                model=model,
                operation=completion_request.operation,
            )
        except APIError as exc:
            self._logging_gateway.warning(
                "CerebrasCompletionGateway.get_completion: "
                "An error was encountered while trying the Cerebras API."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=str(exc),
                cause=exc,
                timeout_applied=self._timeout_seconds,
            ) from exc
        except CompletionGatewayError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "CerebrasCompletionGateway.get_completion: "
                "Unexpected failure while processing completion request."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Unexpected Cerebras completion failure.",
                cause=exc,
                timeout_applied=self._timeout_seconds,
            ) from exc

    def _serialize_create_kwargs(
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

        max_tokens = self._resolve_max_tokens(
            request,
            operation_config=operation_config,
        )
        if max_tokens is not None:
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
        operation: str,
    ) -> CompletionResponse:
        content_parts: list[str] = []
        stream_reasoning_deltas: list[str] = []
        tool_calls_by_key: dict[str, dict[str, Any]] = {}
        stop_reason = None
        usage = None
        role = None
        raw_chunks: list[Any] = []

        async for chunk in stream:
            raw_chunks.append(chunk)
            payload = self._normalize_dict(chunk)
            detail = self._extract_chunk_error(payload)
            if detail is not None:
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=operation,
                    message=detail,
                    timeout_applied=self._timeout_seconds,
                )

            choices = self._resolve_choice_list(chunk, payload)
            if choices:
                choice = choices[0]
                choice_payload = self._normalize_dict(choice)
                finish_reason = choice_payload.get("finish_reason")
                if finish_reason is not None:
                    stop_reason = finish_reason

                delta = choice_payload.get("delta")
                delta_payload = self._normalize_dict(delta)
                if delta_payload:
                    if role is None and isinstance(delta_payload.get("role"), str):
                        role = delta_payload["role"]

                    delta_content = delta_payload.get("content")
                    if isinstance(delta_content, str):
                        content_parts.append(delta_content)

                    delta_reasoning = delta_payload.get("reasoning")
                    if isinstance(delta_reasoning, str):
                        stream_reasoning_deltas.append(delta_reasoning)

                    tool_calls = delta_payload.get("tool_calls")
                    if isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            self._merge_stream_tool_call(
                                tool_calls_by_key,
                                tool_call,
                            )

            chunk_usage = payload.get("usage")
            if chunk_usage is not None:
                usage = self._usage_from_payload(chunk_usage)

        content = "".join(content_parts)
        tool_calls = list(tool_calls_by_key.values())
        message_payload: dict[str, Any] | None = None
        if content or tool_calls:
            message_payload = {
                "role": role or "assistant",
                "content": content,
            }
            if tool_calls:
                message_payload["tool_calls"] = tool_calls

        vendor_fields: dict[str, Any] = {}
        if stream_reasoning_deltas:
            vendor_fields["stream_reasoning_deltas"] = stream_reasoning_deltas

        return CompletionResponse(
            content=content,
            model=model,
            stop_reason=stop_reason,
            message=message_payload,
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
        operation: str,
    ) -> CompletionResponse:
        payload = self._normalize_dict(chat_completion)
        error_detail = self._extract_chunk_error(payload)
        if error_detail is not None:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=error_detail,
                timeout_applied=self._timeout_seconds,
            )

        choices = self._resolve_choice_list(chat_completion, payload)
        if not choices:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message="Cerebras response did not include any completion choices.",
                timeout_applied=self._timeout_seconds,
            )

        choice = choices[0]
        choice_payload = self._normalize_dict(choice)
        message_payload = self._normalize_dict(choice_payload.get("message"))
        content = self._normalize_content(message_payload.get("content"))
        if content is None:
            content = ""

        tool_calls = self._normalize_list_of_dicts(message_payload.get("tool_calls"))
        usage = self._usage_from_payload(payload.get("usage"))

        vendor_fields: dict[str, Any] = {}
        for key in self._response_vendor_keys:
            if key in payload:
                vendor_fields[key] = payload[key]

        if len(choices) > 1:
            vendor_fields["additional_choices"] = [
                self._normalize_dict(extra_choice) for extra_choice in choices[1:]
            ]

        if isinstance(message_payload.get("reasoning"), str):
            vendor_fields["reasoning"] = message_payload["reasoning"]

        return CompletionResponse(
            content=content,
            model=payload.get("model", model),
            stop_reason=choice_payload.get("finish_reason"),
            message=message_payload,
            tool_calls=tool_calls,
            usage=usage,
            vendor_fields=vendor_fields,
            raw=chat_completion,
        )

    @staticmethod
    def _resolve_choice_list(response: Any, payload: dict[str, Any]) -> list[Any]:
        choices = getattr(response, "choices", None)
        if isinstance(choices, list):
            return choices
        payload_choices = payload.get("choices")
        if isinstance(payload_choices, list):
            return payload_choices
        return []

    @classmethod
    def _extract_chunk_error(cls, payload: dict[str, Any]) -> str | None:
        error = payload.get("error")
        if error is None:
            return None

        error_payload = cls._normalize_dict(error)
        if error_payload:
            message = error_payload.get("message")
            code = error_payload.get("code")
            pieces = []
            if isinstance(code, str) and code.strip():
                pieces.append(code.strip())
            if isinstance(message, str) and message.strip():
                pieces.append(message.strip())
            if pieces:
                return ": ".join(pieces)
            return "Cerebras request failed."

        if isinstance(error, str) and error.strip():
            return error.strip()
        return "Cerebras request failed."

    @classmethod
    def _merge_stream_tool_call(
        cls,
        tool_calls_by_key: dict[str, dict[str, Any]],
        tool_call: Any,
    ) -> None:
        payload = cls._normalize_dict(tool_call)
        if payload == {}:
            return

        key = None
        call_id = payload.get("id")
        if isinstance(call_id, str) and call_id.strip():
            key = f"id:{call_id.strip()}"
        elif isinstance(payload.get("index"), int):
            key = f"index:{payload['index']}"
        if key is None:
            key = f"position:{len(tool_calls_by_key)}"

        existing = tool_calls_by_key.get(key)
        if existing is None:
            existing = {}
            tool_calls_by_key[key] = existing

        if isinstance(payload.get("id"), str) and payload["id"].strip():
            existing["id"] = payload["id"].strip()
        if isinstance(payload.get("index"), int):
            existing["index"] = payload["index"]
        if isinstance(payload.get("type"), str):
            existing["type"] = payload["type"]

        function_payload = cls._normalize_dict(payload.get("function"))
        if function_payload:
            existing_function = cls._normalize_dict(existing.get("function"))
            name = function_payload.get("name")
            if isinstance(name, str) and name.strip():
                existing_function["name"] = name.strip()

            arguments = function_payload.get("arguments")
            if isinstance(arguments, str):
                prior_arguments = existing_function.get("arguments")
                if isinstance(prior_arguments, str):
                    existing_function["arguments"] = prior_arguments + arguments
                else:
                    existing_function["arguments"] = arguments

            for extra_key, extra_value in function_payload.items():
                if extra_key in {"name", "arguments"}:
                    continue
                existing_function[extra_key] = extra_value
            existing["function"] = existing_function

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._resolve_api_config().dict[operation]
        except (AttributeError, KeyError) as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing Cerebras operation configuration: {operation}",
                cause=exc,
            ) from exc

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid Cerebras operation configuration: {operation}",
            )

        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Cerebras operation '{operation}' is missing model.",
            )
        if "max_tokens" in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=(
                    f"Cerebras operation '{operation}' includes removed legacy key "
                    "'max_tokens'. Use 'max_completion_tokens'."
                ),
            )

        return cfg

    def _validate_surface_aliases(
        self,
        request: CompletionRequest,
        operation_config: dict[str, Any],
    ) -> None:
        if "openai_api" in request.vendor_params:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=(
                    "CerebrasCompletionGateway: vendor param 'openai_api' is not "
                    "supported. Use 'cerebras_api'."
                ),
                timeout_applied=self._timeout_seconds,
            )

        raw_surface = request.vendor_params.get(
            self._surface_vendor_param,
            operation_config.get("surface", self._chat_surface),
        )
        if not isinstance(raw_surface, str):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message="Invalid Cerebras API surface value. Expected 'chat_completions'.",
                timeout_applied=self._timeout_seconds,
            )
        normalized_surface = raw_surface.strip().lower().replace("-", "_")
        if normalized_surface != self._chat_surface:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message="Invalid Cerebras API surface value. Expected 'chat_completions'.",
                timeout_applied=self._timeout_seconds,
            )

    def _validate_stream_options(self, request: CompletionRequest) -> None:
        stream_options = request.inference.stream_options
        if bool(stream_options):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=(
                    "CerebrasCompletionGateway: inference.stream_options is not supported."
                ),
                timeout_applied=self._timeout_seconds,
            )

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
                provider_label="CerebrasCompletionGateway",
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

    @staticmethod
    def _resolve_max_tokens(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> int | None:
        max_tokens = request.inference.max_completion_tokens
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
                    "CerebrasCompletionGateway: Removed legacy vendor param "
                    f"'{key}' is not supported."
                ),
                timeout_applied=self._timeout_seconds,
            )

    @classmethod
    def _usage_from_payload(cls, usage: Any) -> CompletionUsage | None:
        usage_payload = cls._normalize_dict(usage)
        if usage_payload == {}:
            return None

        vendor_fields: dict[str, Any] = {}
        for key, value in usage_payload.items():
            if key in {"prompt_tokens", "completion_tokens", "total_tokens"}:
                continue
            vendor_fields[key] = value

        return CompletionUsage(
            input_tokens=usage_payload.get("prompt_tokens"),
            output_tokens=usage_payload.get("completion_tokens"),
            total_tokens=usage_payload.get("total_tokens"),
            vendor_fields=vendor_fields,
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
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            dumped = to_dict()
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

        payload = cls._normalize_dict(value)
        if payload:
            return payload
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
