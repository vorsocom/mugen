"""Extension contracts for authenticated WhatsApp webhook changes."""

from __future__ import annotations

__all__ = [
    "WhatsAppWebhookChangeDispatch",
    "WhatsAppWebhookChangeEnvelope",
    "WhatsAppWebhookChangeHandler",
    "WhatsAppWebhookChangeOutcome",
    "WhatsAppWebhookChangeRegistry",
    "normalize_webhook_change_field",
    "safe_webhook_change_field",
]

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
import inspect
import re
from types import MappingProxyType
from typing import Any

_CHANGE_FIELD_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_KNOWN_CHANGE_FIELDS = frozenset(
    {
        "account_alerts",
        "account_review_update",
        "account_update",
        "business_capability_update",
        "flows",
        "message_template_quality_update",
        "message_template_status_update",
        "messages",
        "phone_number_name_update",
        "phone_number_quality_update",
        "security",
        "template_category_update",
    }
)
_KNOWN_EVENT_TYPES = frozenset(
    {
        "FLOW_JSON_VERSION_DEPRECATION",
        "FLOW_STATUS_CHANGE",
    }
)


class WhatsAppWebhookChangeOutcome(StrEnum):
    """Supported outcomes for one registered change handler."""

    HANDLED = "handled"
    IGNORED = "ignored"
    PERMANENT_FAILURE = "permanent_failure"
    RETRYABLE_FAILURE = "retryable_failure"


def normalize_webhook_change_field(
    value: object, *, allow_wildcard: bool = False
) -> str:
    """Return a syntactically valid Meta change field."""

    if allow_wildcard and value == "*":
        return "*"
    if not isinstance(value, str):
        raise ValueError("change_field must be a valid non-empty field name.")
    normalized = value.strip()
    if _CHANGE_FIELD_PATTERN.fullmatch(normalized) is None:
        raise ValueError("change_field must be a valid non-empty field name.")
    return normalized


def safe_webhook_change_field(value: object) -> str:
    """Bound a change field for logs and metric dimensions."""

    return (
        value if isinstance(value, str) and value in _KNOWN_CHANGE_FIELDS else "unknown"
    )


def _safe_event_type(change_value: Mapping[str, Any]) -> str:
    for key in ("event", "event_type"):
        value = change_value.get(key)
        if isinstance(value, str) and value in _KNOWN_EVENT_TYPES:
            return value
    return "unknown"


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)  # pylint: disable=too-many-instance-attributes
class WhatsAppWebhookChangeEnvelope:
    """Immutable, authenticated context passed to a change handler."""

    request_id: str
    payload_fingerprint: str
    client_profile_id: str | None
    object_type: str
    entry_id: str | None
    entry_time: int | str | None
    entry_index: int
    change_index: int
    change_field: str
    change_value: Mapping[str, Any]

    @classmethod
    # pylint: disable=too-many-arguments
    def build(
        cls,
        *,
        request_id: str,
        payload_fingerprint: str,
        client_profile_id: str | None,
        object_type: str,
        entry_id: object,
        entry_time: object,
        entry_index: int,
        change_index: int,
        change_field: object,
        change_value: dict[str, Any],
    ) -> "WhatsAppWebhookChangeEnvelope":
        """Normalize and freeze one authenticated webhook change."""

        normalized_entry_id = (
            entry_id if isinstance(entry_id, str) and entry_id.strip() != "" else None
        )
        normalized_entry_time = (
            entry_time
            if isinstance(entry_time, (int, str)) and not isinstance(entry_time, bool)
            else None
        )
        return cls(
            request_id=request_id,
            payload_fingerprint=payload_fingerprint,
            client_profile_id=client_profile_id,
            object_type=object_type,
            entry_id=normalized_entry_id,
            entry_time=normalized_entry_time,
            entry_index=entry_index,
            change_index=change_index,
            change_field=normalize_webhook_change_field(change_field),
            change_value=_freeze_json(change_value),
        )


WhatsAppWebhookChangeHandler = Callable[
    [WhatsAppWebhookChangeEnvelope],
    WhatsAppWebhookChangeOutcome | str | Awaitable[WhatsAppWebhookChangeOutcome | str],
]


@dataclass(frozen=True, slots=True)
class _HandlerBinding:
    handler: WhatsAppWebhookChangeHandler
    change_field: str
    index: int


@dataclass(frozen=True, slots=True)  # pylint: disable=too-many-instance-attributes
class WhatsAppWebhookChangeDispatch:
    """Aggregated outcomes for all handlers of one webhook change."""

    change_field: str
    safe_change_field: str
    event_type: str
    handler_count: int = 0
    handled_count: int = 0
    ignored_count: int = 0
    permanent_failure_count: int = 0
    retryable_failure_count: int = 0

    @property
    def reason_code(self) -> str:
        """Return the highest-precedence sanitized result reason."""

        if self.retryable_failure_count:
            return "retryable_handler_failure"
        if self.permanent_failure_count:
            return "permanent_handler_failure"
        if self.handler_count == 0:
            return "no_registered_handler"
        if self.handled_count:
            return "change_handler_handled"
        return "change_handler_ignored"


class WhatsAppWebhookChangeRegistry:
    """Deterministically dispatch authenticated changes to extensions."""

    def __init__(self) -> None:
        self._bindings: list[_HandlerBinding] = []

    def register_handler(
        self,
        handler: WhatsAppWebhookChangeHandler,
        *,
        change_field: str,
    ) -> None:
        """Register a handler for one exact field or the ``*`` wildcard."""

        if not callable(handler):
            raise TypeError("handler must be callable.")
        self._bindings.append(
            _HandlerBinding(
                handler=handler,
                change_field=normalize_webhook_change_field(
                    change_field,
                    allow_wildcard=True,
                ),
                index=len(self._bindings),
            )
        )

    def handlers_for(
        self,
        change_field: str,
    ) -> tuple[WhatsAppWebhookChangeHandler, ...]:
        """Return exact and wildcard handlers in registration order."""

        normalized = normalize_webhook_change_field(change_field)
        return tuple(
            binding.handler
            for binding in self._bindings
            if binding.change_field in {normalized, "*"}
        )

    async def dispatch(
        self,
        envelope: WhatsAppWebhookChangeEnvelope,
    ) -> WhatsAppWebhookChangeDispatch:
        """Attempt every matching handler and aggregate sanitized outcomes."""

        handlers = self.handlers_for(envelope.change_field)
        counts = {
            WhatsAppWebhookChangeOutcome.HANDLED: 0,
            WhatsAppWebhookChangeOutcome.IGNORED: 0,
            WhatsAppWebhookChangeOutcome.PERMANENT_FAILURE: 0,
            WhatsAppWebhookChangeOutcome.RETRYABLE_FAILURE: 0,
        }
        for handler in handlers:
            try:
                result = handler(envelope)
                if inspect.isawaitable(result):
                    result = await result
                outcome = WhatsAppWebhookChangeOutcome(result)
            except Exception:  # pylint: disable=broad-exception-caught
                outcome = WhatsAppWebhookChangeOutcome.RETRYABLE_FAILURE
            counts[outcome] += 1

        return WhatsAppWebhookChangeDispatch(
            change_field=envelope.change_field,
            safe_change_field=safe_webhook_change_field(envelope.change_field),
            event_type=_safe_event_type(envelope.change_value),
            handler_count=len(handlers),
            handled_count=counts[WhatsAppWebhookChangeOutcome.HANDLED],
            ignored_count=counts[WhatsAppWebhookChangeOutcome.IGNORED],
            permanent_failure_count=counts[
                WhatsAppWebhookChangeOutcome.PERMANENT_FAILURE
            ],
            retryable_failure_count=counts[
                WhatsAppWebhookChangeOutcome.RETRYABLE_FAILURE
            ],
        )
