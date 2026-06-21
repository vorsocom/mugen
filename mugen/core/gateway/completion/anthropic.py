"""Provides a direct Anthropic Messages completion gateway."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import aiohttp

from mugen.core.contract.gateway.completion import (
    CompletionGatewayError,
    CompletionRequest,
    CompletionResponse,
    ICompletionGateway,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.gateway.completion.anthropic_messages import (
    build_claude_messages_body,
    parse_claude_messages_response,
)
from mugen.core.gateway.completion.timeout_config import (
    parse_bool_like,
    require_fields_in_production,
    resolve_optional_positive_float,
    warn_missing_in_production,
)


# pylint: disable=too-few-public-methods
class AnthropicCompletionGateway(ICompletionGateway):
    """A direct Anthropic Messages completion gateway."""

    _provider = "anthropic"
    _default_base_url = "https://api.anthropic.com"
    _default_version = "2023-06-01"
    _body_passthrough_keys = (
        "container",
        "context_management",
        "metadata",
        "mcp_servers",
        "service_tier",
        "tool_choice",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway
        api_cfg = self._api_cfg()
        self._api_key = self._require_non_empty_string(api_cfg, "key")
        self._base_url = self._resolve_base_url(api_cfg)
        self._version = self._resolve_version(api_cfg)
        self._timeout_seconds = self._resolve_timeout_seconds(api_cfg)
        require_fields_in_production(
            config=self._config,
            provider_label="AnthropicCompletionGateway",
            field_values={"timeout_seconds": self._timeout_seconds},
        )
        self._session: aiohttp.ClientSession | None = None
        self._warn_missing_timeout_in_production()

    def _api_cfg(self) -> Any:
        return getattr(
            getattr(self._config, "anthropic", SimpleNamespace()),
            "api",
            SimpleNamespace(),
        )

    @staticmethod
    def _require_non_empty_string(api_cfg: Any, key: str) -> str:
        raw_value = getattr(api_cfg, key, None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            raise RuntimeError(
                f"Invalid configuration: anthropic.api.{key} is required."
            )
        return raw_value.strip()

    @classmethod
    def _resolve_base_url(cls, api_cfg: Any) -> str:
        raw_value = getattr(api_cfg, "base_url", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            return cls._default_base_url
        return raw_value.strip().rstrip("/")

    @classmethod
    def _resolve_version(cls, api_cfg: Any) -> str:
        raw_value = getattr(api_cfg, "version", None)
        if not isinstance(raw_value, str) or raw_value.strip() == "":
            return cls._default_version
        return raw_value.strip()

    def _resolve_timeout_seconds(self, api_cfg: Any) -> float | None:
        return resolve_optional_positive_float(
            value=getattr(api_cfg, "timeout_seconds", None),
            field_name="timeout_seconds",
            provider_label="AnthropicCompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _warn_missing_timeout_in_production(self) -> None:
        warn_missing_in_production(
            config=self._config,
            provider_label="AnthropicCompletionGateway",
            logging_gateway=self._logging_gateway,
            field_values={"timeout_seconds": self._timeout_seconds},
        )

    async def check_readiness(self) -> None:
        self._resolve_operation_config("classification")
        self._resolve_operation_config("completion")
        try:
            await self._request_json(
                "GET",
                "/v1/models?limit=1",
                operation="readiness",
            )
        except CompletionGatewayError as exc:
            raise RuntimeError(
                "Anthropic completion gateway readiness probe failed."
            ) from exc

    async def aclose(self) -> None:
        if self._session is None:
            return None
        await self._session.close()
        self._session = None
        return None

    async def get_completion(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        completion_request = request
        operation_config = self._resolve_operation_config(completion_request.operation)
        self._reject_streaming(completion_request)
        model = completion_request.model or operation_config["model"]
        body = build_claude_messages_body(
            request=completion_request,
            operation_config=operation_config,
            model=model,
            provider=self._provider,
            provider_label="AnthropicCompletionGateway",
            timeout_applied=self._timeout_seconds,
        )
        for key in self._body_passthrough_keys:
            if key in completion_request.vendor_params:
                body[key] = completion_request.vendor_params[key]

        payload = await self._request_json(
            "POST",
            "/v1/messages",
            operation=completion_request.operation,
            body=body,
        )
        return parse_claude_messages_response(
            payload=payload,
            model=model,
            provider=self._provider,
            raw=payload,
        )

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._config.anthropic.api.dict[operation]
        except (AttributeError, KeyError) as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing Anthropic operation configuration: {operation}",
                cause=exc,
            ) from exc

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid Anthropic operation configuration: {operation}",
            )
        if "model" not in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Anthropic operation '{operation}' is missing model.",
            )
        if "max_tokens" in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=(
                    f"Anthropic operation '{operation}' includes removed legacy key "
                    "'max_tokens'. Use 'max_completion_tokens'."
                ),
            )
        return cfg

    def _reject_streaming(self, request: CompletionRequest) -> None:
        stream = self._parse_bool_like(
            request=request,
            value=request.inference.stream,
            field_name="inference.stream",
        )
        if not stream and "stream" in request.vendor_params:
            stream = self._parse_bool_like(
                request=request,
                value=request.vendor_params["stream"],
                field_name="vendor_params.stream",
            )
        if stream:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=(
                    "AnthropicCompletionGateway stream mode is not yet supported."
                ),
                timeout_applied=self._timeout_seconds,
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
                provider_label="AnthropicCompletionGateway",
            )
        except ValueError as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=str(exc),
                cause=exc,
                timeout_applied=self._timeout_seconds,
            ) from exc

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._session is None:
            timeout = (
                aiohttp.ClientTimeout(total=self._timeout_seconds)
                if self._timeout_seconds is not None
                else None
            )
            self._session = aiohttp.ClientSession(timeout=timeout)

        headers = {
            "anthropic-version": self._version,
            "x-api-key": self._api_key,
        }
        if body is not None:
            headers["content-type"] = "application/json"

        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=body,
            ) as response:
                response_text = await response.text()
                status = int(response.status)
        except (aiohttp.ClientError, asyncio.TimeoutError, TimeoutError) as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Anthropic API request failed: {exc}",
                cause=exc,
                timeout_applied=self._timeout_seconds,
            ) from exc

        if status >= 400:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"{status}: {self._extract_error_message(response_text)}",
                timeout_applied=self._timeout_seconds,
            )
        if response_text.strip() == "":
            return {}
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message="Anthropic API response was not valid JSON.",
                cause=exc,
                timeout_applied=self._timeout_seconds,
            ) from exc
        if isinstance(parsed, dict):
            return parsed
        raise CompletionGatewayError(
            provider=self._provider,
            operation=operation,
            message="Anthropic API response JSON was not an object.",
            timeout_applied=self._timeout_seconds,
        )

    @staticmethod
    def _extract_error_message(response_text: str) -> str:
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError:
            return response_text.strip() or "No detail provided."
        if isinstance(payload, dict):
            error_payload = payload.get("error")
            if isinstance(error_payload, dict):
                message = error_payload.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return response_text.strip() or "No detail provided."
