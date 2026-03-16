"""Turn request primitives for context runtime preparation."""

from __future__ import annotations

__all__ = ["ContextTurnContent", "ContextTurnRequest"]

from dataclasses import dataclass, field
from typing import Any

from mugen.core.contract.context.context_scope import ContextScope

ContextTurnContent = str | dict[str, Any] | list[dict[str, Any]]


def _normalize_payload_list(value: object, *, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a list[dict].")
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{field_name} entries must be dict values.")
        normalized.append(dict(item))
    return normalized


def _normalize_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dict.")
    return dict(value)


@dataclass(frozen=True, slots=True)
class ContextTurnRequest:
    """Typed request for context-engine prepare/commit flow."""

    scope: ContextScope
    user_message: ContextTurnContent
    message_id: str | None = None
    trace_id: str | None = None
    message_context: list[dict[str, Any]] = field(default_factory=list)
    attachment_context: list[dict[str, Any]] = field(default_factory=list)
    ingress_metadata: dict[str, Any] = field(default_factory=dict)
    budget_hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ContextScope):
            raise TypeError("ContextTurnRequest.scope must be ContextScope.")
        if not isinstance(self.user_message, (str, dict, list)):
            raise TypeError(
                "ContextTurnRequest.user_message must be str, dict, or list[dict]."
            )
        if isinstance(self.user_message, list) and not all(
            isinstance(item, dict) for item in self.user_message
        ):
            raise TypeError("ContextTurnRequest.user_message list entries must be dict.")
        object.__setattr__(
            self,
            "message_context",
            _normalize_payload_list(
                self.message_context,
                field_name="ContextTurnRequest.message_context",
            ),
        )
        object.__setattr__(
            self,
            "attachment_context",
            _normalize_payload_list(
                self.attachment_context,
                field_name="ContextTurnRequest.attachment_context",
            ),
        )
        object.__setattr__(
            self,
            "ingress_metadata",
            _normalize_mapping(
                self.ingress_metadata,
                field_name="ContextTurnRequest.ingress_metadata",
            ),
        )
        object.__setattr__(
            self,
            "budget_hints",
            _normalize_mapping(
                self.budget_hints,
                field_name="ContextTurnRequest.budget_hints",
            ),
        )
