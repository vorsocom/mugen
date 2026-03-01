"""Provides a SambaNova chat completion gateway."""

# https://community.sambanova.ai/t/create-chat-completion-api/105

import asyncio
from io import BytesIO
import json
from types import SimpleNamespace
from typing import Any

import pycurl

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    CompletionUsage,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.timeout_config import (
    parse_bool_like,
    require_fields_in_production,
    resolve_optional_positive_float,
    to_timeout_milliseconds,
    warn_missing_in_production,
)


# pylint: disable=too-few-public-methods
class SambaNovaCompletionGateway(ICompletionGateway):
    """A SambaNova chat completion gateway."""

    _provider = "sambanova"
    _vendor_passthrough_keys = (
        "chat_template_kwargs",
        "do_sample",
        "frequency_penalty",
        "logprobs",
        "n",
        "parallel_tool_calls",
        "presence_penalty",
        "reasoning_effort",
        "response_format",
        "seed",
        "tool_choice",
        "tools",
        "top_k",
        "top_logprobs",
        "user",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway
        self._connect_timeout_seconds = self._resolve_optional_positive_float(
            getattr(self._config.sambanova.api, "connect_timeout_seconds", None),
            "connect_timeout_seconds",
        )
        self._read_timeout_seconds = self._resolve_optional_positive_float(
            getattr(self._config.sambanova.api, "read_timeout_seconds", None),
            "read_timeout_seconds",
        )
        require_fields_in_production(
            config=self._config,
            provider_label="SambaNovaCompletionGateway",
            field_values={
                "connect_timeout_seconds": self._connect_timeout_seconds,
                "read_timeout_seconds": self._read_timeout_seconds,
            },
        )
        self._warn_missing_timeout_controls_in_production()

    def _resolve_optional_positive_float(
        self,
        value: Any,
        field_name: str,
    ) -> float | None:
        return resolve_optional_positive_float(
            value=value,
            field_name=field_name,
            provider_label="SambaNovaCompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _warn_missing_timeout_controls_in_production(self) -> None:
        warn_missing_in_production(
            config=self._config,
            provider_label="SambaNovaCompletionGateway",
            logging_gateway=self._logging_gateway,
            field_values={
                "connect_timeout_seconds": self._connect_timeout_seconds,
                "read_timeout_seconds": self._read_timeout_seconds,
            },
        )

    async def get_completion(
        self,
        request: CompletionRequest,
        operation: str = "completion",
    ) -> CompletionResponse:
        completion_request = request
        operation_config = self._resolve_operation_config(completion_request.operation)
        model = completion_request.model or operation_config["model"]

        temperature = completion_request.inference.temperature
        if temperature is None:
            temperature = float(operation_config.get("temp", 0.0))
        top_p = completion_request.inference.top_p
        max_tokens = completion_request.inference.effective_max_tokens
        if max_tokens is None and "max_completion_tokens" in operation_config:
            max_tokens = int(operation_config["max_completion_tokens"])
        if max_tokens is None and "max_tokens" in operation_config:
            max_tokens = int(operation_config["max_tokens"])
        stop = self._resolve_stop_sequences(
            completion_request,
            operation_config=operation_config,
        )
        token_limit_field = self._resolve_token_limit_field(
            completion_request,
            operation_config=operation_config,
        )

        stream = self._resolve_stream(completion_request)
        stream_options = self._resolve_stream_options(completion_request)

        headers: list[str] = [
            self._build_authorization_header(
                completion_request,
                operation_config=operation_config,
            ),
            "Content-Type: application/json",
        ]
        data: dict[str, Any] = {
            "messages": [
                message.to_dict()
                for message in completion_request.messages
            ],
            "model": model,
            "stream": stream,
            "temperature": temperature,
        }
        if stop:
            data["stop"] = stop
        if top_p is not None:
            data["top_p"] = top_p
        if max_tokens is not None:
            data[token_limit_field] = max_tokens
            if (
                token_limit_field == "max_completion_tokens"
                and self._resolve_vendor_bool(
                    completion_request,
                    key="sambanova_emit_legacy_max_tokens",
                    default=False,
                )
            ):
                data["max_tokens"] = max_tokens
        if stream:
            data["stream_options"] = stream_options

        for key in self._vendor_passthrough_keys:
            if key in completion_request.vendor_params:
                data[key] = completion_request.vendor_params[key]

        try:
            status_code, body_text = await asyncio.to_thread(
                self._perform_request,
                headers=headers,
                body=data,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "SambaNovaCompletionGateway.get_completion: "
                "Request execution failed."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Failed to execute SambaNova request.",
                cause=e,
                timeout_applied=self._read_timeout_seconds,
            ) from e

        if status_code >= 400:
            detail = self._extract_http_error(body_text)
            self._logging_gateway.warning(
                "SambaNovaCompletionGateway.get_completion: "
                f"SambaNova API request failed ({detail})."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=detail,
                timeout_applied=self._read_timeout_seconds,
            )

        try:
            if stream:
                return self._parse_streaming_response(
                    model=model,
                    operation=completion_request.operation,
                    payload=body_text,
                )

            payload = json.loads(body_text)
            return self._parse_json_response(model=model, payload=payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            self._logging_gateway.warning(
                "SambaNovaCompletionGateway.get_completion: "
                "Invalid response payload."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Failed to parse SambaNova response payload.",
                cause=e,
                timeout_applied=self._read_timeout_seconds,
            ) from e

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._config.sambanova.api.dict[operation]
        except (AttributeError, KeyError) as e:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing SambaNova operation configuration: {operation}",
                cause=e,
            ) from e

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid SambaNova operation configuration: {operation}",
            )

        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"SambaNova operation '{operation}' is missing model.",
            )

        return cfg

    def _build_authorization_header(
        self,
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> str:
        scheme = self._resolve_auth_scheme(request, operation_config=operation_config)
        if scheme == "basic":
            return f"Authorization: Basic {self._config.sambanova.api.key}"
        return f"Authorization: Bearer {self._config.sambanova.api.key}"

    @staticmethod
    def _resolve_auth_scheme(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> str:
        raw_scheme = request.vendor_params.get(
            "sambanova_auth_scheme",
            operation_config.get("auth_scheme", "bearer"),
        )
        if not isinstance(raw_scheme, str):
            return "bearer"

        normalized = raw_scheme.strip().lower().replace("-", "_")
        if normalized in {"basic", "legacy_basic"}:
            return "basic"
        return "bearer"

    @staticmethod
    def _resolve_token_limit_field(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> str:
        raw_field = request.vendor_params.get(
            "sambanova_token_limit_field",
            operation_config.get("token_limit_field", "max_tokens"),
        )
        if not isinstance(raw_field, str):
            return "max_tokens"

        normalized = raw_field.strip().lower()
        if normalized == "max_completion_tokens":
            return "max_completion_tokens"
        return "max_tokens"

    def _resolve_stream_options(self, request: CompletionRequest) -> dict[str, Any]:
        stream_options = request.inference.stream_options
        resolved: dict[str, Any] = {}
        if isinstance(stream_options, dict) and stream_options:
            resolved = dict(stream_options)

        vendor_stream_options = request.vendor_params.get("stream_options")
        if isinstance(vendor_stream_options, dict) and vendor_stream_options:
            resolved = dict(vendor_stream_options)

        if "include_usage" in request.vendor_params:
            resolved.setdefault(
                "include_usage",
                self._resolve_vendor_bool(
                    request,
                    key="include_usage",
                    default=False,
                ),
            )

        if not resolved:
            resolved = {"include_usage": False}

        return resolved

    def _resolve_stream(self, request: CompletionRequest) -> bool:
        stream = self._parse_bool_like(
            request=request,
            value=request.inference.stream,
            field_name="inference.stream",
        )
        if "stream" in request.vendor_params:
            stream = self._parse_bool_like(
                request=request,
                value=request.vendor_params["stream"],
                field_name="vendor_params.stream",
            )
        return stream

    def _resolve_vendor_bool(
        self,
        request: CompletionRequest,
        *,
        key: str,
        default: bool,
    ) -> bool:
        if key not in request.vendor_params:
            return default
        return self._parse_bool_like(
            request=request,
            value=request.vendor_params[key],
            field_name=f"vendor_params.{key}",
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
                provider_label="SambaNovaCompletionGateway",
            )
        except ValueError as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=str(exc),
                cause=exc,
                timeout_applied=self._read_timeout_seconds,
            ) from exc

    @staticmethod
    def _resolve_stop_sequences(
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> list[str]:
        if request.inference.stop:
            return request.inference.stop

        configured_stop = operation_config.get("stop")
        if isinstance(configured_stop, str) and configured_stop:
            return [configured_stop]
        if isinstance(configured_stop, list):
            return [
                item for item in configured_stop if isinstance(item, str) and item
            ]

        return []

    def _perform_request(
        self,
        *,
        headers: list[str],
        body: dict[str, Any],
    ) -> tuple[int, str]:
        buffer = BytesIO()

        # pylint: disable=c-extension-no-member
        curl = pycurl.Curl()
        try:
            curl.setopt(curl.URL, self._config.sambanova.api.endpoint)
            curl.setopt(curl.POSTFIELDS, json.dumps(body))
            curl.setopt(curl.HTTPHEADER, headers)
            curl.setopt(curl.WRITEFUNCTION, buffer.write)
            curl.setopt(pycurl.SSL_VERIFYPEER, 1)
            curl.setopt(pycurl.SSL_VERIFYHOST, 2)
            if self._connect_timeout_seconds is not None:
                connect_timeout_ms = to_timeout_milliseconds(self._connect_timeout_seconds)
                if connect_timeout_ms is not None:
                    curl.setopt(pycurl.CONNECTTIMEOUT_MS, connect_timeout_ms)
            if self._read_timeout_seconds is not None:
                read_timeout_ms = to_timeout_milliseconds(self._read_timeout_seconds)
                if read_timeout_ms is not None:
                    curl.setopt(pycurl.TIMEOUT_MS, read_timeout_ms)
            curl.perform()
            status_code = int(curl.getinfo(pycurl.RESPONSE_CODE))
        finally:
            curl.close()

        return status_code, buffer.getvalue().decode("utf8")

    @staticmethod
    def _extract_http_error(body_text: str) -> str:
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            return (
                body_text.strip() or "HTTP request failed without JSON error payload."
            )

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("type") or error)
            return str(payload)

        return str(payload)

    def _parse_json_response(
        self,
        *,
        model: str,
        payload: dict[str, Any],
    ) -> CompletionResponse:
        choices = payload["choices"]
        message = choices[0]["message"]
        content = self._normalize_content(message.get("content"))
        if isinstance(content, str):
            content = content.strip()
        if content is None:
            content = ""
        stop_reason = choices[0].get("finish_reason")
        usage = self._usage_from_payload(payload.get("usage"))
        message_payload = self._normalize_dict(message)
        tool_calls = self._normalize_list_of_dicts(message_payload.get("tool_calls"))

        return CompletionResponse(
            content=content,
            model=model,
            stop_reason=stop_reason,
            message=message_payload,
            tool_calls=tool_calls,
            usage=usage,
            raw=payload,
        )

    def _parse_streaming_response(
        self,
        *,
        model: str,
        operation: str,
        payload: str,
    ) -> CompletionResponse:
        content_parts: list[str] = []
        rich_content_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []
        stop_reason = None
        usage = None

        chunks = [
            item.strip() for item in payload.strip().split("\n\n") if item.strip()
        ]
        for chunk in chunks:
            if chunk.startswith("data:"):
                chunk = chunk[5:].strip()
            if chunk == "[DONE]":
                continue

            json_payload = json.loads(chunk)
            if "choices" in json_payload:
                choice = json_payload["choices"][0]
                delta = choice.get("delta", {})
                delta_content = delta.get("content")
                if isinstance(delta_content, str):
                    content_parts.append(delta_content)
                elif delta_content is not None:
                    normalized_content = self._normalize_content(delta_content)
                    if isinstance(normalized_content, dict):
                        rich_content_parts.append(normalized_content)
                    elif isinstance(normalized_content, list):
                        rich_content_parts.extend(normalized_content)

                delta_tool_calls = delta.get("tool_calls")
                if isinstance(delta_tool_calls, list):
                    for delta_tool_call in delta_tool_calls:
                        normalized_tool_call = self._normalize_dict(delta_tool_call)
                        if normalized_tool_call:
                            tool_calls.append(normalized_tool_call)

                if choice.get("finish_reason") is not None:
                    stop_reason = choice.get("finish_reason")
            if "usage" in json_payload:
                usage = self._usage_from_payload(json_payload.get("usage"))
            if "error" in json_payload:
                error = json_payload["error"]
                message = error.get("message") or error.get("type") or str(error)
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=operation,
                    message=str(message),
                )

        content: Any = "".join(content_parts).strip()
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
            raw=payload,
        )

    @staticmethod
    def _usage_from_payload(payload: Any) -> CompletionUsage | None:
        if not isinstance(payload, dict):
            return None

        vendor_fields: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in {"prompt_tokens", "completion_tokens", "total_tokens"}:
                vendor_fields[key] = value

        return CompletionUsage(
            input_tokens=payload.get("prompt_tokens"),
            output_tokens=payload.get("completion_tokens"),
            total_tokens=payload.get("total_tokens"),
            vendor_fields=vendor_fields,
        )

    @staticmethod
    def _normalize_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return {}

    @classmethod
    def _normalize_content(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, dict)):
            return value
        if isinstance(value, list):
            normalized: list[dict[str, Any]] = []
            for item in value:
                item_payload = cls._normalize_dict(item)
                if item_payload:
                    normalized.append(item_payload)
            return normalized
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
