"""Typed data models for IPC request/response contracts."""

__all__ = [
    "IPCCommandRequest",
    "IPCHandlerResult",
    "IPCAggregateError",
    "IPCAggregateResult",
    "IPCCriticalDispatchError",
]

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class IPCCommandRequest:
    """A typed IPC command request passed to service and extensions."""

    platform: str
    command: str
    data: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    correlation_id: str | None = None


@dataclass(slots=True, frozen=True)
class IPCHandlerResult:
    """A normalized result returned by one IPC extension handler."""

    handler: str
    response: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    code: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe response envelope."""
        return {
            "handler": self.handler,
            "ok": self.ok,
            "code": self.code,
            "error": self.error,
            "response": self.response,
        }


@dataclass(slots=True, frozen=True)
class IPCAggregateError:
    """A normalized error captured while aggregating IPC handler results."""

    code: str
    error: str
    handler: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe response envelope."""
        return {
            "code": self.code,
            "error": self.error,
            "handler": self.handler,
        }


@dataclass(slots=True, frozen=True)
class IPCAggregateResult:
    """Aggregate result from dispatching one IPC command."""

    platform: str
    command: str
    expected_handlers: int
    received: int
    duration_ms: int
    results: list[IPCHandlerResult] = field(default_factory=list)
    errors: list[IPCAggregateError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-safe response envelope."""
        return {
            "platform": self.platform,
            "command": self.command,
            "expected_handlers": self.expected_handlers,
            "received": self.received,
            "duration_ms": self.duration_ms,
            "results": [item.to_dict() for item in self.results],
            "errors": [item.to_dict() for item in self.errors],
        }


class IPCCriticalDispatchError(RuntimeError):
    """Raised when a critical IPC handler fails during dispatch."""

    def __init__(
        self,
        *,
        platform: str,
        command: str,
        handler: str | None,
        code: str,
        error: str,
    ) -> None:
        normalized_handler = (
            handler.strip()
            if isinstance(handler, str) and handler.strip() != ""
            else "<unknown>"
        )
        normalized_error = error.strip() if isinstance(error, str) and error.strip() != "" else "unknown error"
        normalized_code = code.strip() if isinstance(code, str) and code.strip() != "" else "unknown"
        super().__init__(
            "Critical IPC dispatch failed "
            f"(platform={platform} command={command} handler={normalized_handler} "
            f"code={normalized_code} error={normalized_error})."
        )
        self.platform = platform
        self.command = command
        self.handler = normalized_handler
        self.code = normalized_code
        self.error = normalized_error
