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
    normalise_completion_request,
)
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=too-few-public-methods
class SambaNovaCompletionGateway(ICompletionGateway):
    """A SambaNova chat completion gateway."""

    _provider = "sambanova"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway

    async def get_completion(
        self,
        request: CompletionRequest | list[dict[str, Any]],
        operation: str = "completion",
    ) -> CompletionResponse:
        completion_request = normalise_completion_request(request, operation=operation)
        operation_config = self._resolve_operation_config(completion_request.operation)
        model = completion_request.model or operation_config["model"]

        temperature = completion_request.inference.temperature
        if temperature is None:
            temperature = float(operation_config.get("temp", 0.0))
        top_p = completion_request.inference.top_p
        max_tokens = completion_request.inference.max_tokens
        stop = completion_request.inference.stop or ["<|eot_id|>"]

        stream = bool(completion_request.vendor_params.get("stream", False))
        include_usage = bool(
            completion_request.vendor_params.get("include_usage", False)
        )

        headers: list[str] = [
            f"Authorization: Basic {self._config.sambanova.api.key}",
            "Content-Type: application/json",
        ]
        data: dict[str, Any] = {
            "messages": completion_request.to_context(),
            "model": model,
            "stream": stream,
            "temperature": temperature,
            "stop": stop,
        }
        if top_p is not None:
            data["top_p"] = top_p
        if max_tokens is not None:
            data["max_tokens"] = max_tokens
        if stream:
            data["stream_options"] = {"include_usage": include_usage}

        for key in [
            "frequency_penalty",
            "presence_penalty",
            "response_format",
            "seed",
            "tool_choice",
            "tools",
            "user",
        ]:
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
        content = message.get("content", "")
        stop_reason = choices[0].get("finish_reason")
        usage = self._usage_from_payload(payload.get("usage"))

        return CompletionResponse(
            content=content.strip() if isinstance(content, str) else "",
            model=model,
            stop_reason=stop_reason,
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

        return CompletionResponse(
            content="".join(content_parts).strip(),
            model=model,
            stop_reason=stop_reason,
            usage=usage,
            raw=payload,
        )

    @staticmethod
    def _usage_from_payload(payload: Any) -> CompletionUsage | None:
        if not isinstance(payload, dict):
            return None

        return CompletionUsage(
            input_tokens=payload.get("prompt_tokens"),
            output_tokens=payload.get("completion_tokens"),
            total_tokens=payload.get("total_tokens"),
        )
