"""Provides an abstract base class for creating chat completion gateways."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from typing import Any

CompletionMessageContent = str | dict[str, Any] | list[dict[str, Any]] | None
CompletionResponseContent = str | dict[str, Any] | list[dict[str, Any]] | None


@dataclass(frozen=True)
class CompletionMessage:
    """A normalised completion message."""

    role: str
    content: CompletionMessageContent

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompletionMessage":
        """Build a message from a dict payload."""
        role = payload.get("role")
        content = payload.get("content")

        if not isinstance(role, str):
            raise ValueError("Message role must be a string.")
        if content is not None and not isinstance(content, (str, dict, list)):
            raise ValueError("Message content must be a string, object, list, or null.")

        if isinstance(content, list) and not all(
            isinstance(item, dict) for item in content
        ):
            raise ValueError("Message content list items must be objects.")

        return cls(role=role, content=content)

    def to_dict(self) -> dict[str, Any]:
        """Convert message to a plain dict."""
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class CompletionInferenceConfig:
    """Provider-agnostic inference controls."""

    max_completion_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] = field(default_factory=list)
    stream: bool = False
    stream_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionReasoningConfig:
    """Provider-neutral reasoning controls."""

    mode: str | None = None
    effort: str | None = None
    budget_tokens: int | None = None
    include_encrypted_state: bool = False
    visibility: str = "opaque"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "CompletionReasoningConfig":
        """Build reasoning controls from a dict payload."""
        if payload is None:
            return cls()
        if not isinstance(payload, dict):
            raise ValueError("Reasoning config must be an object.")

        budget_tokens = payload.get("budget_tokens")
        if budget_tokens is not None:
            budget_tokens = int(budget_tokens)

        visibility = payload.get("visibility", "opaque")
        if not isinstance(visibility, str):
            raise ValueError("Reasoning visibility must be a string.")

        mode = payload.get("mode")
        if mode is not None and not isinstance(mode, str):
            raise ValueError("Reasoning mode must be a string or null.")

        effort = payload.get("effort")
        if effort is not None and not isinstance(effort, str):
            raise ValueError("Reasoning effort must be a string or null.")

        return cls(
            mode=mode,
            effort=effort,
            budget_tokens=budget_tokens,
            include_encrypted_state=bool(payload.get("include_encrypted_state", False)),
            visibility=visibility,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert reasoning controls to a plain dict."""
        return {
            "mode": self.mode,
            "effort": self.effort,
            "budget_tokens": self.budget_tokens,
            "include_encrypted_state": self.include_encrypted_state,
            "visibility": self.visibility,
        }

    def is_configured(self) -> bool:
        """Return whether any reasoning behavior was explicitly requested."""
        return any(
            [
                self.mode is not None,
                self.effort is not None,
                self.budget_tokens is not None,
                self.include_encrypted_state,
            ]
        )


@dataclass(frozen=True)
class CompletionTool:
    """Provider-neutral model tool definition."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    strict: bool | None = None
    kind: str = "function"
    provider_hints: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompletionTool":
        """Build a normalized tool definition from a dict payload."""
        if not isinstance(payload, dict):
            raise ValueError("Completion tool must be an object.")

        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Completion tool name is required.")

        description = payload.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("Completion tool description must be a string or null.")

        input_schema = payload.get("input_schema")
        if input_schema is None:
            input_schema = payload.get("parameters")
        if input_schema is None:
            input_schema = {"type": "object", "properties": {}}
        if not isinstance(input_schema, dict):
            raise ValueError("Completion tool input_schema must be an object.")

        kind = payload.get("kind", payload.get("type", "function"))
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("Completion tool kind must be a non-empty string.")

        provider_hints = payload.get("provider_hints")
        if provider_hints is None:
            provider_hints = {}
        if not isinstance(provider_hints, dict):
            raise ValueError("Completion tool provider_hints must be an object.")

        strict = payload.get("strict")
        if strict is not None:
            strict = bool(strict)

        return cls(
            name=name.strip(),
            description=description,
            input_schema=dict(input_schema),
            strict=strict,
            kind=kind.strip(),
            provider_hints=dict(provider_hints),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the normalized tool definition to a plain dict."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "strict": self.strict,
            "kind": self.kind,
            "provider_hints": dict(self.provider_hints),
        }


@dataclass(frozen=True)
class CompletionToolCall:
    """Provider-neutral model tool call."""

    id: str | None
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    provider_item: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompletionToolCall":
        """Build a normalized tool call from common provider shapes."""
        if not isinstance(payload, dict):
            raise ValueError("Completion tool call must be an object.")

        function_payload = payload.get("function")
        function_data = function_payload if isinstance(function_payload, dict) else {}

        name = payload.get("name") or function_data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Completion tool call name is required.")

        raw_arguments = payload.get("arguments")
        if raw_arguments is None:
            raw_arguments = function_data.get("arguments")
        if raw_arguments is None:
            raw_arguments = payload.get("input")

        arguments = _coerce_arguments(raw_arguments)

        tool_call_id = (
            payload.get("call_id") or payload.get("id") or payload.get("tool_use_id")
        )
        if tool_call_id is not None and not isinstance(tool_call_id, str):
            tool_call_id = str(tool_call_id)

        return cls(
            id=tool_call_id,
            name=name.strip(),
            arguments=arguments,
            provider_item=dict(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the normalized tool call to a plain dict."""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": dict(self.arguments),
            "provider_item": dict(self.provider_item),
        }


@dataclass(frozen=True)
class CompletionToolResult:
    """Provider-neutral result for one model tool call."""

    tool_call_id: str
    name: str | None = None
    content: Any = None
    is_error: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompletionToolResult":
        """Build a normalized tool result from a dict payload."""
        if not isinstance(payload, dict):
            raise ValueError("Completion tool result must be an object.")

        tool_call_id = payload.get("tool_call_id") or payload.get("call_id")
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise ValueError("Completion tool result tool_call_id is required.")

        name = payload.get("name")
        if name is not None and not isinstance(name, str):
            name = str(name)

        return cls(
            tool_call_id=tool_call_id.strip(),
            name=name,
            content=payload.get("content"),
            is_error=bool(payload.get("is_error", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert the normalized tool result to a plain dict."""
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
            "is_error": self.is_error,
        }


@dataclass(frozen=True)
class CompletionContinuationState:
    """Opaque provider continuation state for reasoning/tool workflows."""

    provider: str | None = None
    response_id: str | None = None
    conversation_id: str | None = None
    output_items: list[dict[str, Any]] = field(default_factory=list)
    reasoning_items: list[dict[str, Any]] = field(default_factory=list)
    thinking_blocks: list[dict[str, Any]] = field(default_factory=list)
    redacted_thinking_blocks: list[dict[str, Any]] = field(default_factory=list)
    provider_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any] | None,
    ) -> "CompletionContinuationState | None":
        """Build continuation state from a dict payload."""
        if payload is None:
            return None
        if not isinstance(payload, dict):
            raise ValueError("Completion continuation state must be an object.")

        return cls(
            provider=_optional_string(payload.get("provider")),
            response_id=_optional_string(payload.get("response_id")),
            conversation_id=_optional_string(payload.get("conversation_id")),
            output_items=_list_of_dicts(payload.get("output_items")),
            reasoning_items=_list_of_dicts(payload.get("reasoning_items")),
            thinking_blocks=_list_of_dicts(payload.get("thinking_blocks")),
            redacted_thinking_blocks=_list_of_dicts(
                payload.get("redacted_thinking_blocks")
            ),
            provider_state=dict(payload.get("provider_state") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert continuation state to a plain dict for durable replay."""
        return {
            "provider": self.provider,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "output_items": [dict(item) for item in self.output_items],
            "reasoning_items": [dict(item) for item in self.reasoning_items],
            "thinking_blocks": [dict(item) for item in self.thinking_blocks],
            "redacted_thinking_blocks": [
                dict(item) for item in self.redacted_thinking_blocks
            ],
            "provider_state": dict(self.provider_state),
        }

    def to_redacted_dict(self) -> dict[str, Any]:
        """Convert continuation state to a log-safe summary."""
        return {
            "provider": self.provider,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "output_item_count": len(self.output_items),
            "reasoning_item_count": len(self.reasoning_items),
            "thinking_block_count": len(self.thinking_blocks),
            "redacted_thinking_block_count": len(self.redacted_thinking_blocks),
            "provider_state_keys": sorted(str(key) for key in self.provider_state),
        }


@dataclass(frozen=True)
class CompletionRequest:
    """Normalized completion request payload."""

    messages: list[CompletionMessage]
    operation: str = "completion"
    model: str | None = None
    inference: CompletionInferenceConfig = field(
        default_factory=CompletionInferenceConfig
    )
    reasoning: CompletionReasoningConfig | None = None
    tools: list[CompletionTool] = field(default_factory=list)
    tool_results: list[CompletionToolResult] = field(default_factory=list)
    continuation_state: CompletionContinuationState | None = None
    vendor_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionUsage:
    """Normalized token-usage details."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    vendor_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResponse:
    """Normalized completion response payload."""

    content: CompletionResponseContent
    model: str | None = None
    stop_reason: str | None = None
    message: dict[str, Any] | None = None
    tool_calls: list[CompletionToolCall | dict[str, Any]] = field(default_factory=list)
    output_items: list[dict[str, Any]] = field(default_factory=list)
    reasoning_state: CompletionContinuationState | None = None
    provider_state: dict[str, Any] = field(default_factory=dict)
    usage: CompletionUsage | None = None
    vendor_fields: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


class CompletionGatewayError(RuntimeError):
    """Raised when a completion gateway cannot fulfill a request."""

    def __init__(
        self,
        *,
        provider: str,
        operation: str,
        message: str,
        cause: Exception | None = None,
        timeout_applied: float | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.cause = cause
        self.timeout_applied = timeout_applied


class ICompletionGateway(ABC):  # pylint: disable=too-few-public-methods
    """A chat completion gateway base class."""

    @abstractmethod
    async def check_readiness(self) -> None:
        """Validate provider readiness for startup fail-fast checks."""

    @abstractmethod
    async def aclose(self) -> None:
        """Close provider resources asynchronously."""

    @abstractmethod
    async def get_completion(
        self,
        request: CompletionRequest,
    ) -> CompletionResponse:
        """Get LLM response from normalized completion request data."""


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    return normalized or None


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _coerce_arguments(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}
