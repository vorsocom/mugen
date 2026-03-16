"""Shared helpers for provider-safe completion message serialization."""

from __future__ import annotations

__all__ = [
    "serialize_completion_message_content",
    "serialize_completion_message_dict",
]

import json
from typing import Any

from mugen.core.contract.gateway.completion import CompletionMessage


def serialize_completion_message_content(content: Any) -> str:
    """Convert normalized message content into text-safe provider input."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, (dict, list)):
        return json.dumps(content, ensure_ascii=True)
    return str(content)


def serialize_completion_message_dict(message: CompletionMessage) -> dict[str, str]:
    """Serialize one normalized message into a text-only provider payload."""
    return {
        "role": message.role,
        "content": serialize_completion_message_content(message.content),
    }
