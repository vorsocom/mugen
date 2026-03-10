"""Domain entities for the context_engine plugin."""

from __future__ import annotations

__all__ = [
    "ContextCacheRecordDE",
    "ContextCommitLedgerDE",
    "ContextContributorBindingDE",
    "ContextEventLogDE",
    "ContextMemoryRecordDE",
    "ContextPolicyDE",
    "ContextProfileDE",
    "ContextSourceBindingDE",
    "ContextStateSnapshotDE",
    "ContextTraceDE",
    "ContextTracePolicyDE",
]

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ContextProfileDE(BaseDE, TenantScopedDEMixin):
    """Context profile definition for one tenant/platform/channel segment."""

    name: str | None = None
    description: str | None = None
    platform: str | None = None
    channel_key: str | None = None
    service_route_key: str | None = None
    client_profile_key: str | None = None
    policy_id: uuid.UUID | None = None
    persona: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextPolicyDE(BaseDE, TenantScopedDEMixin):
    """Stored context policy configuration."""

    policy_key: str | None = None
    description: str | None = None
    budget_json: dict[str, Any] | None = None
    redaction_json: dict[str, Any] | None = None
    retention_json: dict[str, Any] | None = None
    contributor_allow: list[str] | None = None
    contributor_deny: list[str] | None = None
    source_allow: list[str] | None = None
    source_deny: list[str] | None = None
    trace_enabled: bool | None = None
    cache_enabled: bool | None = None
    is_active: bool | None = None
    is_default: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextContributorBindingDE(BaseDE, TenantScopedDEMixin):
    """Binding row controlling contributor participation."""

    binding_key: str | None = None
    contributor_key: str | None = None
    platform: str | None = None
    channel_key: str | None = None
    service_route_key: str | None = None
    priority: int | None = None
    is_enabled: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextSourceBindingDE(BaseDE, TenantScopedDEMixin):
    """Binding row controlling source selection overlays."""

    source_kind: str | None = None
    source_key: str | None = None
    platform: str | None = None
    channel_key: str | None = None
    service_route_key: str | None = None
    locale: str | None = None
    category: str | None = None
    is_enabled: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextTracePolicyDE(BaseDE, TenantScopedDEMixin):
    """Stored trace capture policy."""

    name: str | None = None
    capture_prepare: bool | None = None
    capture_commit: bool | None = None
    capture_selected_items: bool | None = None
    capture_dropped_items: bool | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextStateSnapshotDE(BaseDE, TenantScopedDEMixin):
    """Runtime bounded state snapshot for one scoped conversation."""

    scope_key: str | None = None
    platform: str | None = None
    channel_id: str | None = None
    room_id: str | None = None
    sender_id: str | None = None
    conversation_id: str | None = None
    case_id: str | None = None
    workflow_id: str | None = None
    current_objective: str | None = None
    entities: dict[str, Any] | None = None
    constraints: list[str] | None = None
    unresolved_slots: list[str] | None = None
    commitments: list[str] | None = None
    safety_flags: list[str] | None = None
    routing: dict[str, Any] | None = None
    summary: str | None = None
    revision: int | None = None
    last_message_id: str | None = None
    last_trace_id: str | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextEventLogDE(BaseDE, TenantScopedDEMixin):
    """Runtime recent-turn event record."""

    scope_key: str | None = None
    sequence_no: int | None = None
    role: str | None = None
    content: str | dict[str, Any] | list[dict[str, Any]] | None = None
    message_id: str | None = None
    trace_id: str | None = None
    source: str | None = None
    occurred_at: datetime | None = None


@dataclass
class ContextMemoryRecordDE(BaseDE, TenantScopedDEMixin):
    """Runtime long-term memory record."""

    scope_partition: dict[str, Any] | None = None
    memory_type: str | None = None
    memory_key: str | None = None
    subject: str | None = None
    content: dict[str, Any] | str | None = None
    provenance: dict[str, Any] | None = None
    confidence: float | None = None
    expires_at: datetime | None = None
    is_deleted: bool | None = None
    tags: list[str] | None = None
    commit_token: str | None = None
    attributes: dict[str, Any] | None = None


@dataclass
class ContextCacheRecordDE(BaseDE, TenantScopedDEMixin):
    """Runtime cache record."""

    namespace: str | None = None
    cache_key: str | None = None
    payload: dict[str, Any] | list[Any] | None = None
    expires_at: datetime | None = None
    last_hit_at: datetime | None = None
    hit_count: int | None = None


@dataclass
class ContextCommitLedgerDE(BaseDE, TenantScopedDEMixin):
    """Runtime commit-token ledger record."""

    scope_key: str | None = None
    commit_token: str | None = None
    prepared_fingerprint: str | None = None
    commit_state: str | None = None
    expires_at: datetime | None = None
    last_error: str | None = None
    result_json: dict[str, Any] | None = None


@dataclass
class ContextTraceDE(BaseDE, TenantScopedDEMixin):
    """Runtime trace capture record."""

    scope_key: str | None = None
    trace_id: str | None = None
    message_id: str | None = None
    stage: str | None = None
    selected_items: list[dict[str, Any]] | None = None
    dropped_items: list[dict[str, Any]] | None = None
    payload: dict[str, Any] | None = None
    occurred_at: datetime | None = None
