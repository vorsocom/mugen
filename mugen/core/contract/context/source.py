"""Structured source identity and policy rules for context artifacts."""

from __future__ import annotations

__all__ = [
    "ContextSourcePolicyEffect",
    "ContextSourceRef",
    "ContextSourceRule",
]

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Context source values must be strings or None.")
    normalized = value.strip()
    return normalized or None


def _normalize_required_text(value: object, *, field_name: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        raise ValueError(f"{field_name} is required.")
    return normalized


def _normalize_mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dict.")
    return dict(value)


class ContextSourcePolicyEffect(str, Enum):
    """Stable effect values for source-policy rules."""

    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class ContextSourceRef:
    """Stable source identity emitted by contributors for policy and dedupe."""

    kind: str
    source_key: str | None = None
    source_id: str | None = None
    canonical_locator: str | None = None
    segment_id: str | None = None
    locale: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _normalize_required_text(self.kind, field_name="ContextSourceRef.kind"),
        )
        object.__setattr__(
            self,
            "source_key",
            _normalize_optional_text(self.source_key),
        )
        object.__setattr__(
            self,
            "source_id",
            _normalize_optional_text(self.source_id),
        )
        object.__setattr__(
            self,
            "canonical_locator",
            _normalize_optional_text(self.canonical_locator),
        )
        object.__setattr__(
            self,
            "segment_id",
            _normalize_optional_text(self.segment_id),
        )
        object.__setattr__(
            self,
            "locale",
            _normalize_optional_text(self.locale),
        )
        object.__setattr__(
            self,
            "category",
            _normalize_optional_text(self.category),
        )
        object.__setattr__(
            self,
            "metadata",
            _normalize_mapping(
                self.metadata,
                field_name="ContextSourceRef.metadata",
            ),
        )

    def identity_payload(self) -> dict[str, Any]:
        """Return the stable source identity used by trace and dedupe logic."""
        return {
            "kind": self.kind,
            "source_key": self.source_key,
            "source_id": self.source_id,
            "canonical_locator": self.canonical_locator,
            "segment_id": self.segment_id,
            "locale": self.locale,
            "category": self.category,
        }


@dataclass(frozen=True, slots=True)
class ContextSourceRule:
    """One resolved allow/deny rule evaluated by the engine."""

    effect: ContextSourcePolicyEffect
    kind: str | None = None
    source_key: str | None = None
    locale: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.effect, ContextSourcePolicyEffect):
            raise TypeError(
                "ContextSourceRule.effect must be ContextSourcePolicyEffect."
            )
        object.__setattr__(self, "kind", _normalize_optional_text(self.kind))
        object.__setattr__(
            self,
            "source_key",
            _normalize_optional_text(self.source_key),
        )
        object.__setattr__(self, "locale", _normalize_optional_text(self.locale))
        object.__setattr__(self, "category", _normalize_optional_text(self.category))
        object.__setattr__(
            self,
            "metadata",
            _normalize_mapping(
                self.metadata,
                field_name="ContextSourceRule.metadata",
            ),
        )

    def requires_source_ref(self) -> bool:
        """Whether this rule needs structured source identity beyond kind."""
        return any(
            value is not None
            for value in (
                self.source_key,
                self.locale,
                self.category,
            )
        )

    def matches(
        self,
        source: ContextSourceRef | None,
        *,
        source_kind: str | None = None,
    ) -> bool:
        """Return whether `source` satisfies this rule."""
        candidate_kind = (
            source.kind if source is not None else _normalize_optional_text(source_kind)
        )
        if self.kind is not None and self.kind != candidate_kind:
            return False
        if source is None:
            return not self.requires_source_ref()
        if self.source_key is not None and self.source_key != source.source_key:
            return False
        if self.locale is not None and self.locale != source.locale:
            return False
        if self.category is not None and self.category != source.category:
            return False
        return True

    def descriptor(self) -> dict[str, Any]:
        """Return a stable trace-friendly descriptor for this rule."""
        return {
            "effect": self.effect.value,
            "kind": self.kind,
            "source_key": self.source_key,
            "locale": self.locale,
            "category": self.category,
        }
