"""Context policy, budget, redaction, and retention primitives."""

from __future__ import annotations

__all__ = [
    "ContextBudget",
    "ContextLaneBudget",
    "ContextPolicy",
    "ContextRedactionPolicy",
    "ContextRetentionPolicy",
]

from dataclasses import dataclass, field
from typing import Any

from mugen.core.contract.context.source import ContextSourceRule


@dataclass(frozen=True, slots=True)
class ContextLaneBudget:
    """Per-lane defaults and reservations used by selection."""

    lane: str
    min_items: int = 0
    max_items: int | None = None
    reserved_tokens: int = 0
    allow_spillover: bool = True


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Budget envelope controlling artifact selection and compilation size."""

    max_total_tokens: int = 4000
    soft_max_total_tokens: int | None = None
    max_selected_artifacts: int = 24
    max_recent_turns: int = 12
    max_recent_messages: int = 24
    max_evidence_items: int = 12
    max_prefix_tokens: int = 2500
    adaptive_trimming: str = "none"
    lane_budgets: tuple[ContextLaneBudget, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextRedactionPolicy:
    """Sensitivity and redaction policy for context assembly."""

    redact_sensitive: bool = True
    blocked_sensitivity_labels: tuple[str, ...] = ()
    allowed_sensitivity_labels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextRetentionPolicy:
    """Retention and writeback policy for context runtime artifacts."""

    allow_long_term_memory: bool = True
    require_partition_for_global_memory: bool = True
    memory_ttl_seconds: int | None = None
    trace_ttl_seconds: int | None = None
    cache_ttl_seconds: int | None = None
    commit_token_ttl_seconds: int | None = 900


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    """Resolved policy for one prepared context turn."""

    profile_key: str | None = None
    policy_key: str | None = None
    budget: ContextBudget = field(default_factory=ContextBudget)
    redaction: ContextRedactionPolicy = field(default_factory=ContextRedactionPolicy)
    retention: ContextRetentionPolicy = field(default_factory=ContextRetentionPolicy)
    contributor_allow: tuple[str, ...] = ()
    contributor_deny: tuple[str, ...] = ()
    source_allow: tuple[str, ...] = ()
    source_deny: tuple[str, ...] = ()
    source_rules: tuple[ContextSourceRule, ...] = ()
    trace_enabled: bool = True
    trace_capture_prepare: bool = True
    trace_capture_commit: bool = True
    trace_capture_selected: bool = True
    trace_capture_dropped: bool = True
    cache_enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
