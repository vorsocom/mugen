"""Contracts for safe conversational Knowledge Pack selection."""

from __future__ import annotations

__all__ = [
    "ApprovedKnowledgeResult",
    "IKnowledgeConversationSelector",
    "KnowledgeConversationCandidate",
    "KnowledgeConversationDecisionType",
    "KnowledgeConversationSelection",
    "KnowledgeConversationSelectionPolicy",
    "KnowledgeConversationSelectionProvenance",
]

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any
import uuid


def _require_uuid(value: uuid.UUID, field_name: str) -> uuid.UUID:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field_name} must be a UUID.")
    return value


def _normalize_required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if normalized == "":
        raise ValueError(f"{field_name} must be non-empty.")
    return normalized


def _normalize_similarity(value: float, field_name: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a number.")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0.0 or normalized > 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1.")
    return normalized


# pylint: disable=too-many-instance-attributes
@dataclass(slots=True, frozen=True)
class ApprovedKnowledgeResult:
    """Relationally rehydrated approved content with retrieval provenance."""

    tenant_id: uuid.UUID
    knowledge_pack_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID
    knowledge_entry_id: uuid.UUID
    knowledge_entry_revision_id: uuid.UUID
    knowledge_scope_id: uuid.UUID
    entry_key: str
    title: str
    body: str | None
    body_json: dict[str, Any] | None
    channel: str | None
    locale: str | None
    category: str | None
    service_route_key: str | None
    client_profile_key: str | None
    service_profile_id: uuid.UUID | None
    similarity: float | None
    distance: float | None
    projection_provider: str
    projection_target_fingerprint: str
    knowledge_pack_active: bool = True
    knowledge_pack_version_status: str = "published"
    knowledge_entry_active: bool = True
    knowledge_entry_revision_status: str = "published"
    knowledge_scope_active: bool = True
    projection_ready: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "knowledge_pack_id",
            "knowledge_pack_version_id",
            "knowledge_entry_id",
            "knowledge_entry_revision_id",
            "knowledge_scope_id",
        ):
            _require_uuid(getattr(self, field_name), field_name)
        if self.service_profile_id is not None:
            _require_uuid(self.service_profile_id, "service_profile_id")
        for field_name in (
            "entry_key",
            "title",
            "projection_provider",
            "projection_target_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_required_text(getattr(self, field_name), field_name),
            )
        if self.body is None and self.body_json is None:
            raise ValueError("An approved result must contain relational content.")
        if self.body_json is not None and not isinstance(self.body_json, dict):
            raise TypeError("body_json must be a dictionary or None.")
        if self.similarity is not None:
            object.__setattr__(
                self,
                "similarity",
                _normalize_similarity(self.similarity, "similarity"),
            )
        if self.distance is not None:
            if isinstance(self.distance, bool):
                raise TypeError("distance must be a number.")
            distance = float(self.distance)
            if not isfinite(distance) or distance < 0.0:
                raise ValueError("distance must be a non-negative finite number.")
            object.__setattr__(self, "distance", distance)

    @property
    def approved_for_selection(self) -> bool:
        """Return whether captured relational state remains selection-eligible."""
        return (
            self.knowledge_pack_active is True
            and self.knowledge_pack_version_status == "published"
            and self.knowledge_entry_active is True
            and self.knowledge_entry_revision_status == "published"
            and self.knowledge_scope_active is True
            and self.projection_ready is True
        )


@dataclass(slots=True, frozen=True)
class KnowledgeConversationCandidate:
    """An approved relational result addressable by a caller-owned identifier."""

    candidate_id: uuid.UUID
    result: ApprovedKnowledgeResult

    def __post_init__(self) -> None:
        _require_uuid(self.candidate_id, "candidate_id")
        if not isinstance(self.result, ApprovedKnowledgeResult):
            raise TypeError("result must be an ApprovedKnowledgeResult.")
        if not self.result.approved_for_selection:
            raise ValueError("result is not approved for conversational selection.")


@dataclass(slots=True, frozen=True)
class KnowledgeConversationSelectionPolicy:
    """Configurable deterministic and optional adjudication thresholds."""

    auto_answer_min_similarity: float
    adjudication_min_similarity: float
    winner_margin: float
    candidate_limit: int
    max_answers: int
    llm_adjudication_enabled: bool

    def __post_init__(self) -> None:
        for field_name in (
            "auto_answer_min_similarity",
            "adjudication_min_similarity",
            "winner_margin",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalize_similarity(getattr(self, field_name), field_name),
            )
        if self.adjudication_min_similarity > self.auto_answer_min_similarity:
            raise ValueError(
                "adjudication_min_similarity cannot exceed "
                "auto_answer_min_similarity."
            )
        if (
            not isinstance(self.candidate_limit, int)
            or isinstance(self.candidate_limit, bool)
            or self.candidate_limit <= 0
        ):
            raise ValueError("candidate_limit must be a positive integer.")
        if (
            not isinstance(self.max_answers, int)
            or isinstance(self.max_answers, bool)
            or self.max_answers < 1
            or self.max_answers > 3
        ):
            raise ValueError("max_answers must be between 1 and 3.")
        if self.max_answers > self.candidate_limit:
            raise ValueError("max_answers cannot exceed candidate_limit.")
        if not isinstance(self.llm_adjudication_enabled, bool):
            raise TypeError("llm_adjudication_enabled must be a boolean.")


class KnowledgeConversationDecisionType(str, Enum):
    """Normalized conversational selection outcomes."""

    ANSWER = "answer"
    CLARIFY = "clarify"
    DECLINE = "decline"
    UNAVAILABLE = "unavailable"


@dataclass(slots=True, frozen=True)
class KnowledgeConversationSelectionProvenance:
    """Relational provenance retained for one selected answer."""

    candidate_id: uuid.UUID
    tenant_id: uuid.UUID
    knowledge_pack_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID
    knowledge_entry_id: uuid.UUID
    knowledge_entry_revision_id: uuid.UUID
    knowledge_scope_id: uuid.UUID
    service_profile_id: uuid.UUID | None

    @classmethod
    def from_candidate(
        cls,
        candidate: KnowledgeConversationCandidate,
    ) -> "KnowledgeConversationSelectionProvenance":
        """Copy immutable audit provenance without customer-facing content."""
        result = candidate.result
        return cls(
            candidate_id=candidate.candidate_id,
            tenant_id=result.tenant_id,
            knowledge_pack_id=result.knowledge_pack_id,
            knowledge_pack_version_id=result.knowledge_pack_version_id,
            knowledge_entry_id=result.knowledge_entry_id,
            knowledge_entry_revision_id=result.knowledge_entry_revision_id,
            knowledge_scope_id=result.knowledge_scope_id,
            service_profile_id=result.service_profile_id,
        )


@dataclass(slots=True, frozen=True)
class KnowledgeConversationSelection:
    """Safe normalized decision containing identifiers and provenance only."""

    decision_type: KnowledgeConversationDecisionType
    selected_candidate_ids: tuple[uuid.UUID, ...]
    selected_provenance: tuple[KnowledgeConversationSelectionProvenance, ...]
    semantic_retrieval_used: bool
    llm_adjudication_used: bool
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision_type, KnowledgeConversationDecisionType):
            raise TypeError(
                "decision_type must be a KnowledgeConversationDecisionType."
            )
        if self.decision_type is KnowledgeConversationDecisionType.ANSWER:
            if not 1 <= len(self.selected_candidate_ids) <= 3:
                raise ValueError(
                    "Answer decisions must select one to three candidates."
                )
        elif self.selected_candidate_ids or self.selected_provenance:
            raise ValueError("Non-answer decisions cannot select candidates.")
        if len(self.selected_provenance) != len(self.selected_candidate_ids):
            raise ValueError("Selected provenance must match selected candidate IDs.")
        if tuple(item.candidate_id for item in self.selected_provenance) != (
            self.selected_candidate_ids
        ):
            raise ValueError("Selected provenance is not aligned with candidate IDs.")
        for candidate_id in self.selected_candidate_ids:
            _require_uuid(candidate_id, "selected_candidate_id")
        if not isinstance(self.semantic_retrieval_used, bool):
            raise TypeError("semantic_retrieval_used must be a boolean.")
        if not isinstance(self.llm_adjudication_used, bool):
            raise TypeError("llm_adjudication_used must be a boolean.")
        object.__setattr__(
            self,
            "reason_code",
            _normalize_required_text(self.reason_code, "reason_code"),
        )


class IKnowledgeConversationSelector(ABC):  # pylint: disable=too-few-public-methods
    """Select approved conversational answers without generating response prose."""

    @abstractmethod
    async def select(
        self,
        *,
        query_text: str,
        candidates: tuple[KnowledgeConversationCandidate, ...],
        policy: KnowledgeConversationSelectionPolicy,
    ) -> KnowledgeConversationSelection:
        """Return a normalized answer, clarification, decline, or failure decision."""
