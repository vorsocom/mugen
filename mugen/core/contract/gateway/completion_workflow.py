"""Shared helpers for reasoning-workflow completion contracts."""

from __future__ import annotations

from typing import Any

from mugen.core.contract.gateway.completion import (
    CompletionContinuationState,
    CompletionResponse,
    CompletionToolCall,
    CompletionUsage,
)

REDACTED_VALUE = "<redacted>"

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "data",
    "encrypted_content",
    "key",
    "password",
    "provider_state",
    "reasoning",
    "reasoning_items",
    "redacted_thinking",
    "redacted_thinking_blocks",
    "secret",
    "signature",
    "thinking",
    "thinking_blocks",
    "token",
}


def normalize_completion_tool_call(value: Any) -> CompletionToolCall | None:
    """Normalize a provider or contract tool call into CompletionToolCall."""
    if isinstance(value, CompletionToolCall):
        return value
    if isinstance(value, dict):
        try:
            return CompletionToolCall.from_dict(value)
        except ValueError:
            return None
    return None


def serialize_completion_tool_call(value: Any) -> dict[str, Any]:
    """Serialize a tool call while accepting legacy provider dicts."""
    if isinstance(value, CompletionToolCall):
        return value.to_dict()
    if isinstance(value, dict):
        return dict(value)
    return {"provider_item": redact_provider_payload(value)}


def serialize_completion_usage(usage: CompletionUsage | None) -> dict[str, Any] | None:
    """Serialize usage, including reasoning tokens when available."""
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "vendor_fields": redact_provider_payload(dict(usage.vendor_fields)),
    }


def serialize_completion_response_for_log(
    completion: CompletionResponse | None,
) -> dict[str, Any] | None:
    """Serialize a completion response for append-only steps and logs."""
    if completion is None:
        return None
    return {
        "content": completion.content,
        "model": completion.model,
        "stop_reason": completion.stop_reason,
        "message": redact_provider_payload(completion.message),
        "tool_calls": [
            redact_provider_payload(serialize_completion_tool_call(item))
            for item in completion.tool_calls
        ],
        "output_item_count": len(completion.output_items),
        "reasoning_state": serialize_continuation_state_for_log(
            completion.reasoning_state
        ),
        "provider_state": redact_provider_payload(completion.provider_state),
        "usage": serialize_completion_usage(completion.usage),
        "vendor_fields": redact_provider_payload(dict(completion.vendor_fields)),
    }


def serialize_continuation_state_for_log(
    state: CompletionContinuationState | dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Serialize continuation state without exposing opaque reasoning content."""
    if state is None:
        return None
    if isinstance(state, CompletionContinuationState):
        return state.to_redacted_dict()
    if isinstance(state, dict):
        return CompletionContinuationState.from_dict(state).to_redacted_dict()
    return {"provider_state": REDACTED_VALUE}


def redact_provider_payload(value: Any) -> Any:
    """Recursively redact provider reasoning, credentials, and opaque state."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                redacted[key] = REDACTED_VALUE
                continue
            redacted[key] = redact_provider_payload(item)
        return redacted

    if isinstance(value, list):
        return [redact_provider_payload(item) for item in value]

    if isinstance(value, tuple):
        return tuple(redact_provider_payload(item) for item in value)

    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    if normalized in _SENSITIVE_KEYS:
        return True
    if normalized.endswith("_api_key"):
        return True
    if normalized.endswith("_token"):
        return True
    if normalized.endswith("_secret"):
        return True
    return False
