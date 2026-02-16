"""Provides an abstract base class for creating chat completion gateways."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] = field(default_factory=list)
    stream: bool = False
    stream_options: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_max_tokens(self) -> int | None:
        """Unified token limit where max_completion_tokens wins over max_tokens."""
        if self.max_completion_tokens is not None:
            return self.max_completion_tokens
        return self.max_tokens


@dataclass(frozen=True)
class CompletionRequest:
    """Normalized completion request payload."""

    messages: list[CompletionMessage]
    operation: str = "completion"
    model: str | None = None
    inference: CompletionInferenceConfig = field(
        default_factory=CompletionInferenceConfig
    )
    vendor_params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_context(
        cls,
        context: list[dict[str, Any]],
        operation: str = "completion",
    ) -> "CompletionRequest":
        """Build a request from legacy context payloads."""
        if not isinstance(context, list):
            raise ValueError("Context must be a list.")

        messages = [CompletionMessage.from_dict(item) for item in context]
        return cls(messages=messages, operation=operation)

    def to_context(self) -> list[dict[str, Any]]:
        """Convert request back to legacy context payloads."""
        return [message.to_dict() for message in self.messages]


@dataclass(frozen=True)
class CompletionUsage:
    """Normalized token-usage details."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    vendor_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompletionResponse:
    """Normalized completion response payload."""

    content: CompletionResponseContent
    model: str | None = None
    stop_reason: str | None = None
    message: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
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
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.operation = operation
        self.cause = cause


def normalise_completion_request(
    request: CompletionRequest | list[dict[str, Any]],
    *,
    operation: str = "completion",
) -> CompletionRequest:
    """Normalise request inputs during migration to the typed contract."""
    if isinstance(request, CompletionRequest):
        return request

    return CompletionRequest.from_context(request, operation=operation)


class ICompletionGateway(ABC):  # pylint: disable=too-few-public-methods
    """A chat completion gateway base class."""

    @abstractmethod
    async def get_completion(
        self,
        request: CompletionRequest | list[dict[str, Any]],
        operation: str = "completion",
    ) -> CompletionResponse:
        """Get LLM response from normalized completion request data."""
