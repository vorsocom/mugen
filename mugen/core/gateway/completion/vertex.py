"""Provides a GCP Vertex completion gateway backed by Gemini generateContent."""

from __future__ import annotations

import asyncio
from io import BytesIO
import importlib
import json
import threading
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

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
class VertexCompletionGateway(ICompletionGateway):
    """A GCP Vertex Gemini completion gateway."""

    _provider = "vertex"
    _cloud_platform_scope = "https://www.googleapis.com/auth/cloud-platform"
    _removed_legacy_vendor_param_keys = (
        "use_legacy_max_tokens",
        "stream",
        "stream_options",
    )

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        super().__init__()
        self._config = config
        self._logging_gateway = logging_gateway
        self._location = self._resolve_location()
        self._project = self._resolve_project()
        self._static_access_token = self._resolve_optional_api_string("access_token")

        self._connect_timeout_seconds = self._resolve_optional_positive_float(
            getattr(self._api_cfg(), "connect_timeout_seconds", None),
            "connect_timeout_seconds",
        )
        self._read_timeout_seconds = self._resolve_optional_positive_float(
            getattr(self._api_cfg(), "read_timeout_seconds", None),
            "read_timeout_seconds",
        )
        require_fields_in_production(
            config=self._config,
            provider_label="VertexCompletionGateway",
            field_values={
                "connect_timeout_seconds": self._connect_timeout_seconds,
                "read_timeout_seconds": self._read_timeout_seconds,
            },
        )
        self._warn_missing_timeout_controls_in_production()

        self._adc_lock = threading.Lock()
        self._adc_credentials: Any | None = None
        self._adc_request_class: Any | None = None
        self._adc_project_id: str | None = None

    def _api_cfg(self) -> Any:
        return getattr(
            getattr(getattr(self._config, "gcp", SimpleNamespace()), "vertex", SimpleNamespace()),
            "api",
            SimpleNamespace(),
        )

    def _resolve_optional_api_string(self, key: str) -> str | None:
        raw_value = getattr(self._api_cfg(), key, None)
        if not isinstance(raw_value, str):
            return None
        normalized = raw_value.strip()
        if normalized == "":
            return None
        return normalized

    def _resolve_location(self) -> str:
        location = self._resolve_optional_api_string("location")
        if location is None:
            raise RuntimeError(
                "Invalid configuration: VertexCompletionGateway.location is required."
            )
        return location

    def _resolve_project(self) -> str | None:
        return self._resolve_optional_api_string("project")

    def _resolve_optional_positive_float(
        self,
        value: Any,
        field_name: str,
    ) -> float | None:
        return resolve_optional_positive_float(
            value=value,
            field_name=field_name,
            provider_label="VertexCompletionGateway",
            logging_gateway=self._logging_gateway,
        )

    def _warn_missing_timeout_controls_in_production(self) -> None:
        warn_missing_in_production(
            config=self._config,
            provider_label="VertexCompletionGateway",
            logging_gateway=self._logging_gateway,
            field_values={
                "connect_timeout_seconds": self._connect_timeout_seconds,
                "read_timeout_seconds": self._read_timeout_seconds,
            },
        )

    async def check_readiness(self) -> None:
        classification_cfg = self._resolve_operation_config("classification")
        completion_cfg = self._resolve_operation_config("completion")
        probe_model = completion_cfg.get("model") or classification_cfg.get("model")

        timeout_seconds = self._read_timeout_seconds
        if timeout_seconds is None:
            timeout_seconds = 10.0

        probe_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "ping"}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 1,
            },
        }

        try:
            status_code, body_text = await asyncio.wait_for(
                asyncio.to_thread(
                    self._perform_request,
                    model=probe_model.strip(),
                    body=probe_body,
                ),
                timeout=timeout_seconds,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise RuntimeError("Vertex completion gateway readiness probe failed.") from exc

        if 200 <= int(status_code) < 300:
            return
        if self._is_expected_probe_validation_response(status_code, body_text):
            return
        if int(status_code) in {401, 403}:
            raise RuntimeError(
                "Vertex completion gateway readiness probe failed: authentication error."
            )
        if int(status_code) >= 500:
            raise RuntimeError(
                "Vertex completion gateway readiness probe failed: provider unavailable."
            )
        raise RuntimeError("Vertex completion gateway readiness probe failed.")

    async def aclose(self) -> None:
        return None

    async def get_completion(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        completion_request = request
        self._validate_removed_legacy_vendor_params(completion_request)
        operation_config = self._resolve_operation_config(completion_request.operation)
        model = completion_request.model or operation_config["model"]

        stream = self._resolve_stream(completion_request)
        if stream:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=(
                    "VertexCompletionGateway: stream mode is not yet supported."
                ),
                timeout_applied=self._read_timeout_seconds,
            )

        body = self._serialize_request_body(
            completion_request,
            operation_config=operation_config,
        )

        try:
            status_code, body_text = await asyncio.to_thread(
                self._perform_request,
                model=model,
                body=body,
            )
        except CompletionGatewayError:
            raise
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.warning(
                "VertexCompletionGateway.get_completion: Request execution failed."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Failed to execute Vertex request.",
                cause=exc,
                timeout_applied=self._read_timeout_seconds,
            ) from exc

        if int(status_code) >= 400:
            detail = self._extract_http_error(body_text)
            self._logging_gateway.warning(
                "VertexCompletionGateway.get_completion: "
                f"Vertex API request failed ({detail})."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message=detail,
                timeout_applied=self._read_timeout_seconds,
            )

        try:
            payload = json.loads(body_text)
            return self._parse_json_response(
                model=model,
                operation=completion_request.operation,
                payload=payload,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            self._logging_gateway.warning(
                "VertexCompletionGateway.get_completion: Invalid response payload."
            )
            raise CompletionGatewayError(
                provider=self._provider,
                operation=completion_request.operation,
                message="Failed to parse Vertex response payload.",
                cause=exc,
                timeout_applied=self._read_timeout_seconds,
            ) from exc

    def _resolve_operation_config(self, operation: str) -> dict[str, Any]:
        try:
            cfg = self._api_cfg().dict[operation]
        except (AttributeError, KeyError) as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Missing Vertex operation configuration: {operation}",
                cause=exc,
            ) from exc

        if not isinstance(cfg, dict):
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Invalid Vertex operation configuration: {operation}",
            )

        model = cfg.get("model")
        if not isinstance(model, str) or model.strip() == "":
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=f"Vertex operation '{operation}' is missing model.",
            )

        if "max_tokens" in cfg:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message=(
                    f"Vertex operation '{operation}' includes removed legacy key "
                    "'max_tokens'. Use 'max_completion_tokens'."
                ),
            )

        return cfg

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
                    "VertexCompletionGateway: Removed legacy vendor param "
                    f"'{key}' is not supported."
                ),
                timeout_applied=self._read_timeout_seconds,
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
                provider_label="VertexCompletionGateway",
            )
        except ValueError as exc:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=request.operation,
                message=str(exc),
                cause=exc,
                timeout_applied=self._read_timeout_seconds,
            ) from exc

    def _serialize_request_body(
        self,
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> dict[str, Any]:
        contents, system_instruction = self._serialize_messages(request)

        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]

        payload: dict[str, Any] = {
            "contents": contents,
        }
        if system_instruction is not None:
            payload["systemInstruction"] = system_instruction

        generation_config = self._build_generation_config(
            request,
            operation_config=operation_config,
        )
        if generation_config:
            payload["generationConfig"] = generation_config

        vendor_params = request.vendor_params
        if isinstance(vendor_params.get("safety_settings"), list):
            payload["safetySettings"] = vendor_params["safety_settings"]
        if isinstance(vendor_params.get("tools"), list):
            payload["tools"] = vendor_params["tools"]
        if isinstance(vendor_params.get("tool_config"), dict):
            payload["toolConfig"] = vendor_params["tool_config"]
        cached_content = vendor_params.get("cached_content")
        if isinstance(cached_content, str) and cached_content.strip() != "":
            payload["cachedContent"] = cached_content.strip()

        return payload

    def _build_generation_config(
        self,
        request: CompletionRequest,
        *,
        operation_config: dict[str, Any],
    ) -> dict[str, Any]:
        generation_config: dict[str, Any] = {}

        max_tokens = request.inference.max_completion_tokens
        if max_tokens is None and "max_completion_tokens" in operation_config:
            max_tokens = int(operation_config["max_completion_tokens"])
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = int(max_tokens)

        temperature = request.inference.temperature
        if temperature is None and "temp" in operation_config:
            temperature = float(operation_config["temp"])
        if temperature is not None:
            generation_config["temperature"] = float(temperature)

        top_p = request.inference.top_p
        if top_p is None and "top_p" in operation_config:
            top_p = float(operation_config["top_p"])
        if top_p is not None:
            generation_config["topP"] = float(top_p)

        stop_sequences = self._resolve_stop_sequences(
            request,
            operation_config=operation_config,
        )
        if stop_sequences:
            generation_config["stopSequences"] = stop_sequences

        response_mime_type = request.vendor_params.get("response_mime_type")
        if isinstance(response_mime_type, str) and response_mime_type.strip() != "":
            generation_config["responseMimeType"] = response_mime_type.strip()

        response_schema = request.vendor_params.get("response_schema")
        if isinstance(response_schema, (dict, list)):
            generation_config["responseSchema"] = response_schema

        candidate_count = request.vendor_params.get("candidate_count")
        if candidate_count not in [None, ""]:
            try:
                parsed_candidate_count = int(candidate_count)
            except (TypeError, ValueError) as exc:
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=request.operation,
                    message="Vertex candidate_count must be a positive integer.",
                    cause=exc,
                    timeout_applied=self._read_timeout_seconds,
                ) from exc
            if parsed_candidate_count <= 0:
                raise CompletionGatewayError(
                    provider=self._provider,
                    operation=request.operation,
                    message="Vertex candidate_count must be greater than 0.",
                    timeout_applied=self._read_timeout_seconds,
                )
            generation_config["candidateCount"] = parsed_candidate_count

        return generation_config

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
                item
                for item in configured_stop
                if isinstance(item, str) and item != ""
            ]
        return []

    def _serialize_messages(
        self,
        request: CompletionRequest,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        contents: list[dict[str, Any]] = []
        system_parts: list[str] = []

        for message in request.messages:
            role = message.role.strip().lower()
            serialized_content = self._serialize_text_content(message.content)
            if role == "system":
                system_parts.append(serialized_content)
                continue

            if role == "assistant":
                vertex_role = "model"
                text_value = serialized_content
            elif role == "user":
                vertex_role = "user"
                text_value = serialized_content
            else:
                vertex_role = "user"
                text_value = f"[{message.role}] {serialized_content}"

            contents.append(
                {
                    "role": vertex_role,
                    "parts": [{"text": text_value}],
                }
            )

        if not system_parts:
            return contents, None

        return (
            contents,
            {
                "parts": [{"text": "\n\n".join(system_parts)}],
            },
        )

    @staticmethod
    def _serialize_text_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        if isinstance(content, (dict, list)):
            return json.dumps(content, ensure_ascii=True)
        return str(content)

    def _perform_request(
        self,
        *,
        model: str,
        body: dict[str, Any],
    ) -> tuple[int, str]:
        endpoint = self._build_endpoint(model=model)
        access_token = self._resolve_access_token_sync()

        buffer = BytesIO()

        # pylint: disable=c-extension-no-member
        curl = pycurl.Curl()
        try:
            curl.setopt(curl.URL, endpoint)
            curl.setopt(curl.POSTFIELDS, json.dumps(body, ensure_ascii=True))
            curl.setopt(
                curl.HTTPHEADER,
                [
                    f"Authorization: Bearer {access_token}",
                    "Content-Type: application/json",
                ],
            )
            curl.setopt(curl.WRITEFUNCTION, buffer.write)
            curl.setopt(pycurl.SSL_VERIFYPEER, 1)
            curl.setopt(pycurl.SSL_VERIFYHOST, 2)
            if self._connect_timeout_seconds is not None:
                curl.setopt(
                    pycurl.CONNECTTIMEOUT_MS,
                    to_timeout_milliseconds(self._connect_timeout_seconds),
                )
            if self._read_timeout_seconds is not None:
                curl.setopt(
                    pycurl.TIMEOUT_MS,
                    to_timeout_milliseconds(self._read_timeout_seconds),
                )
            curl.perform()
            status_code = int(curl.getinfo(pycurl.RESPONSE_CODE))
        finally:
            curl.close()

        return status_code, buffer.getvalue().decode("utf-8")

    def _build_endpoint(
        self,
        *,
        model: str,
    ) -> str:
        normalized_model = model.strip()
        if normalized_model == "":
            raise RuntimeError("Vertex completion gateway model must be non-empty.")

        quoted_location = quote(self._location, safe="")
        endpoint_base = f"https://{quoted_location}-aiplatform.googleapis.com"

        if normalized_model.startswith("projects/"):
            normalized_model_path = normalized_model.lstrip("/")
            return f"{endpoint_base}/v1/{normalized_model_path}:generateContent"

        project = self._resolve_project_for_request_sync()
        quoted_project = quote(project, safe="")

        if normalized_model.startswith("publishers/"):
            normalized_model_path = normalized_model.lstrip("/")
            return (
                f"{endpoint_base}/v1/projects/{quoted_project}/locations/"
                f"{quoted_location}/{normalized_model_path}:generateContent"
            )

        quoted_model = quote(normalized_model, safe="")
        return (
            f"{endpoint_base}/v1/projects/{quoted_project}/locations/{quoted_location}/"
            f"publishers/google/models/{quoted_model}:generateContent"
        )

    def _resolve_project_for_request_sync(self) -> str:
        if isinstance(self._project, str) and self._project != "":
            return self._project

        _ = self._resolve_access_token_sync()
        if isinstance(self._adc_project_id, str) and self._adc_project_id != "":
            return self._adc_project_id

        raise RuntimeError(
            "Vertex completion gateway requires gcp.vertex.api.project when "
            "ADC did not return a project id."
        )

    def _resolve_access_token_sync(self) -> str:
        if isinstance(self._static_access_token, str) and self._static_access_token != "":
            return self._static_access_token

        self._ensure_adc_loaded_sync()
        credentials = self._adc_credentials
        request_class = self._adc_request_class
        if credentials is None or request_class is None:
            raise RuntimeError(
                "Vertex completion gateway failed to initialize ADC credentials."
            )

        token = getattr(credentials, "token", None)
        is_valid = bool(getattr(credentials, "valid", False))
        if not is_valid or not isinstance(token, str) or token.strip() == "":
            try:
                credentials.refresh(request_class())
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError(
                    "Vertex completion gateway failed to refresh ADC access token."
                ) from exc
            token = getattr(credentials, "token", None)

        if not isinstance(token, str) or token.strip() == "":
            raise RuntimeError(
                "Vertex completion gateway could not resolve a non-empty access token."
            )

        return token.strip()

    def _ensure_adc_loaded_sync(self) -> None:
        if self._adc_credentials is not None and self._adc_request_class is not None:
            return

        with self._adc_lock:
            if self._adc_credentials is not None and self._adc_request_class is not None:
                return

            google_auth_module, transport_requests_module = self._import_google_auth_modules()
            request_class = getattr(transport_requests_module, "Request", None)
            if callable(request_class) is not True:
                raise RuntimeError(
                    "Vertex completion gateway failed to load google-auth request transport."
                )

            try:
                credentials, project_id = google_auth_module.default(
                    scopes=[self._cloud_platform_scope]
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                raise RuntimeError(
                    "Vertex completion gateway failed to load ADC credentials."
                ) from exc

            self._adc_credentials = credentials
            self._adc_request_class = request_class
            if isinstance(project_id, str) and project_id.strip() != "":
                self._adc_project_id = project_id.strip()

    @staticmethod
    def _import_google_auth_modules() -> tuple[Any, Any]:
        try:
            google_auth_module = importlib.import_module("google.auth")
            transport_requests_module = importlib.import_module(
                "google.auth.transport.requests"
            )
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Vertex completion gateway requires google-auth when "
                "gcp.vertex.api.access_token is not configured."
            ) from exc
        return google_auth_module, transport_requests_module

    @staticmethod
    def _extract_http_error(body_text: str) -> str:
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            return body_text.strip() or "HTTP request failed without JSON error payload."

        if not isinstance(payload, dict):
            return str(payload)

        error_payload = payload.get("error")
        if not isinstance(error_payload, dict):
            return str(payload)

        error_message = str(error_payload.get("message") or error_payload.get("status") or error_payload)
        error_code = error_payload.get("code")
        if error_code is None:
            return error_message
        return f"{error_code}: {error_message}"

    @staticmethod
    def _is_expected_probe_validation_response(
        status_code: int,
        body_text: str,
    ) -> bool:
        if int(status_code) not in {400, 422}:
            return False

        error_text = VertexCompletionGateway._extract_http_error(body_text).lower()
        if error_text == "":
            return False
        if any(
            token in error_text
            for token in ("unauthorized", "forbidden", "permission", "credential")
        ):
            return False
        if "model" in error_text and "not found" in error_text:
            return False
        return any(
            token in error_text
            for token in ("invalid", "required", "validation", "contents", "request")
        )

    def _parse_json_response(
        self,
        *,
        model: str,
        operation: str,
        payload: dict[str, Any],
    ) -> CompletionResponse:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise CompletionGatewayError(
                provider=self._provider,
                operation=operation,
                message="Vertex response did not include any completion candidates.",
            )

        primary_candidate = self._normalize_dict(candidates[0])
        content_payload = self._normalize_dict(primary_candidate.get("content"))
        parts = self._normalize_list_of_dicts(content_payload.get("parts"))
        text_parts: list[str] = []
        structured_parts: list[dict[str, Any]] = []
        tool_calls: list[dict[str, Any]] = []

        for part in parts:
            text_value = part.get("text")
            if isinstance(text_value, str):
                text_parts.append(text_value)
                continue

            function_call = self._normalize_dict(part.get("functionCall"))
            if function_call:
                tool_calls.append(self._function_call_to_tool_call(function_call))
                structured_parts.append(part)
                continue

            structured_parts.append(part)

        content: Any = "".join(text_parts).strip()
        if content == "" and structured_parts:
            content = structured_parts

        usage = self._usage_from_payload(payload.get("usageMetadata"))
        vendor_fields: dict[str, Any] = {}
        for key in ("modelVersion", "promptFeedback", "responseId"):
            if key in payload:
                vendor_fields[key] = payload[key]
        if len(candidates) > 1:
            vendor_fields["additional_candidates"] = candidates[1:]
        if structured_parts:
            vendor_fields["structured_content_parts"] = structured_parts
        if "safetyRatings" in primary_candidate:
            vendor_fields["safety_ratings"] = primary_candidate["safetyRatings"]

        message_payload = {
            "role": "assistant",
            "content": content,
        }

        return CompletionResponse(
            content=content,
            model=payload.get("modelVersion", model),
            stop_reason=primary_candidate.get("finishReason"),
            message=message_payload,
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
            if key not in {
                "promptTokenCount",
                "candidatesTokenCount",
                "totalTokenCount",
            }:
                vendor_fields[key] = value

        return CompletionUsage(
            input_tokens=payload.get("promptTokenCount"),
            output_tokens=payload.get("candidatesTokenCount"),
            total_tokens=payload.get("totalTokenCount"),
            vendor_fields=vendor_fields,
        )

    @staticmethod
    def _function_call_to_tool_call(function_call: dict[str, Any]) -> dict[str, Any]:
        args = function_call.get("args")
        if isinstance(args, str):
            serialized_args = args
        elif args is None:
            serialized_args = "{}"
        else:
            serialized_args = json.dumps(args, ensure_ascii=True)

        tool_call = {
            "type": "function",
            "function": {
                "name": function_call.get("name"),
                "arguments": serialized_args,
            },
        }
        if "id" in function_call:
            tool_call["id"] = function_call["id"]
        return tool_call

    @staticmethod
    def _normalize_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return {}

    @classmethod
    def _normalize_list_of_dicts(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in value:
            payload = cls._normalize_dict(item)
            if payload:
                normalized.append(payload)
        return normalized
