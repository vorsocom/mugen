"""Provides an abstract base class for creating chat completion gateways."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompletionMessage:
    """A normalised completion message."""

    role: str
    content: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompletionMessage":
        """Build a message from a dict payload."""
        role = payload.get("role")
        content = payload.get("content")

        if not isinstance(role, str):
            raise ValueError("Message role must be a string.")
        if not isinstance(content, str):
            raise ValueError("Message content must be a string.")

        return cls(role=role, content=content)

    def to_dict(self) -> dict[str, str]:
        """Convert message to a plain dict."""
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class CompletionInferenceConfig:
    """Provider-agnostic inference controls."""

    max_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: list[str] = field(default_factory=list)


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

    def to_context(self) -> list[dict[str, str]]:
        """Convert request back to legacy context payloads."""
        return [message.to_dict() for message in self.messages]


@dataclass(frozen=True)
class CompletionUsage:
    """Normalized token-usage details."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class CompletionResponse:
    """Normalized completion response payload."""

    content: str
    model: str | None = None
    stop_reason: str | None = None
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
