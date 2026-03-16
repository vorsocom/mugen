"""Typed context artifacts, provenance, and selection metadata."""

from __future__ import annotations

__all__ = [
    "ContextArtifact",
    "ContextCandidate",
    "ContextGuardResult",
    "ContextProvenance",
    "ContextSelectionReason",
]

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mugen.core.contract.context.source import ContextSourceRef

ContextArtifactContent = str | dict[str, Any] | list[dict[str, Any]] | None


class ContextSelectionReason(str, Enum):
    """Stable selection and drop reasons tracked in bundles and traces."""

    SELECTED = "selected"
    DROPPED_BUDGET = "dropped_budget"
    DROPPED_DUPLICATE = "dropped_duplicate"
    DROPPED_GUARD = "dropped_guard"
    DROPPED_POLICY = "dropped_policy"
    DROPPED_SOURCE_POLICY = "dropped_source_policy"
    DROPPED_TENANT_MISMATCH = "dropped_tenant_mismatch"
    REDACTED = "redacted"
    VETOED = "vetoed"


@dataclass(frozen=True, slots=True)
class ContextProvenance:
    """Origin metadata carried with every context artifact."""

    contributor: str
    source_kind: str
    source_id: str | None = None
    source: ContextSourceRef | None = None
    title: str | None = None
    uri: str | None = None
    tenant_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextArtifact:
    """Provider-neutral artifact emitted by contributors."""

    artifact_id: str
    lane: str
    kind: str
    content: ContextArtifactContent
    provenance: ContextProvenance
    render_class: str | None = None
    title: str | None = None
    summary: str | None = None
    trust: float | None = None
    freshness: float | None = None
    estimated_token_cost: int = 0
    sensitivity: tuple[str, ...] = ()
    cache_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """Rankable candidate wrapper around a context artifact."""

    artifact: ContextArtifact
    contributor: str
    priority: int = 0
    score: float | None = None
    selected: bool = False
    selection_reason: ContextSelectionReason | None = None
    reason_detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextGuardResult:
    """Explicit pass/drop result returned by a guard implementation."""

    passed_candidates: tuple[ContextCandidate, ...]
    dropped_candidates: tuple[ContextCandidate, ...] = ()
