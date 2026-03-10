"""SQLAlchemy models for the context_engine plugin."""

from __future__ import annotations

__all__ = [
    "ContextCacheRecord",
    "ContextCommitLedger",
    "ContextContributorBinding",
    "ContextEventLog",
    "ContextMemoryRecord",
    "ContextPolicy",
    "ContextProfile",
    "ContextSourceBinding",
    "ContextStateSnapshot",
    "ContextTrace",
    "ContextTracePolicy",
    "metadata",
]

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

_SCHEMA = "mugen"


class ContextProfile(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """ACP-managed context profile row."""

    __tablename__ = "context_engine_context_profile"

    name: Mapped[str] = mapped_column(CITEXT(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    platform: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True, index=True)
    channel_key: Mapped[str | None] = mapped_column(
        CITEXT(64), nullable=True, index=True
    )
    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    client_profile_key: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{_SCHEMA}.context_engine_context_policy.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    persona: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="ux_ctxeng_profile__tenant_name"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_ctxeng_profile__name"),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_ctxeng_profile__service_route_nonempty_if_set",
        ),
        {"schema": _SCHEMA},
    )


class ContextPolicy(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """ACP-managed context policy row."""

    __tablename__ = "context_engine_context_policy"

    policy_key: Mapped[str] = mapped_column(CITEXT(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    budget_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    redaction_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    retention_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    contributor_allow: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    contributor_deny: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_allow: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_deny: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    trace_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )
    cache_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "policy_key", name="ux_ctxeng_policy__tenant_key"
        ),
        CheckConstraint(
            "length(btrim(policy_key)) > 0",
            name="ck_ctxeng_policy__policy_key",
        ),
        {"schema": _SCHEMA},
    )


class ContextContributorBinding(
    ModelBase,
    TenantScopedMixin,
):  # pylint: disable=too-few-public-methods
    """ACP-managed contributor binding row."""

    __tablename__ = "context_engine_context_contributor_binding"

    binding_key: Mapped[str] = mapped_column(CITEXT(128), nullable=False)
    contributor_key: Mapped[str] = mapped_column(
        CITEXT(128), nullable=False, index=True
    )
    platform: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True, index=True)
    channel_key: Mapped[str | None] = mapped_column(
        CITEXT(64), nullable=True, index=True
    )
    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    priority: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "binding_key",
            name="ux_ctxeng_contributor_binding__tenant_key",
        ),
        CheckConstraint(
            "length(btrim(binding_key)) > 0",
            name="ck_ctxeng_contributor_binding__binding_key",
        ),
        CheckConstraint(
            "length(btrim(contributor_key)) > 0",
            name="ck_ctxeng_contributor_binding__contributor_key",
        ),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_ctxeng_contributor_binding__service_route_nonempty_if_set",
        ),
        {"schema": _SCHEMA},
    )


class ContextSourceBinding(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """ACP-managed source binding row."""

    __tablename__ = "context_engine_context_source_binding"

    source_kind: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)
    source_key: Mapped[str] = mapped_column(CITEXT(128), nullable=False)
    platform: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True, index=True)
    channel_key: Mapped[str | None] = mapped_column(
        CITEXT(64), nullable=True, index=True
    )
    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    locale: Mapped[str | None] = mapped_column(CITEXT(32), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True, index=True)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_kind",
            "source_key",
            name="ux_ctxeng_source_binding__tenant_kind_key",
        ),
        CheckConstraint(
            "length(btrim(source_kind)) > 0",
            name="ck_ctxeng_source_binding__source_kind",
        ),
        CheckConstraint(
            "length(btrim(source_key)) > 0",
            name="ck_ctxeng_source_binding__source_key",
        ),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_ctxeng_source_binding__service_route_nonempty_if_set",
        ),
        {"schema": _SCHEMA},
    )


class ContextTracePolicy(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """ACP-managed trace policy row."""

    __tablename__ = "context_engine_context_trace_policy"

    name: Mapped[str] = mapped_column(CITEXT(128), nullable=False)
    capture_prepare: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )
    capture_commit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )
    capture_selected_items: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )
    capture_dropped_items: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "name",
            name="ux_ctxeng_trace_policy__tenant_name",
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_ctxeng_trace_policy__name"),
        {"schema": _SCHEMA},
    )


class ContextStateSnapshot(
    ModelBase,
    TenantScopedMixin,
):  # pylint: disable=too-few-public-methods
    """Runtime bounded control-state snapshot."""

    __tablename__ = "context_engine_context_state_snapshot"

    scope_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False)
    platform: Mapped[str | None] = mapped_column(CITEXT(64), nullable=True, index=True)
    channel_id: Mapped[str | None] = mapped_column(
        CITEXT(128), nullable=True, index=True
    )
    room_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True, index=True)
    sender_id: Mapped[str | None] = mapped_column(
        CITEXT(255), nullable=True, index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(
        CITEXT(255), nullable=True, index=True
    )
    case_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True, index=True)
    workflow_id: Mapped[str | None] = mapped_column(
        CITEXT(255), nullable=True, index=True
    )
    current_objective: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    entities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    constraints: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    unresolved_slots: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    commitments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    safety_flags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    routing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    revision: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )
    last_message_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    last_trace_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "scope_key", name="ux_ctxeng_state__tenant_scope"
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_state__scope_key",
        ),
        {"schema": _SCHEMA},
    )


class ContextEventLog(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """Runtime recent-turn event log."""

    __tablename__ = "context_engine_context_event_log"

    scope_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(CITEXT(32), nullable=False)
    content: Mapped[dict | list | str | None] = mapped_column(JSONB, nullable=True)
    message_id: Mapped[str | None] = mapped_column(
        CITEXT(255), nullable=True, index=True
    )
    trace_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope_key",
            "sequence_no",
            name="ux_ctxeng_event__tenant_scope_seq",
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_event__scope_key",
        ),
        CheckConstraint("length(btrim(role)) > 0", name="ck_ctxeng_event__role"),
        Index(
            "ix_ctxeng_event__tenant_scope_occurred",
            "tenant_id",
            "scope_key",
            "occurred_at",
        ),
        {"schema": _SCHEMA},
    )


class ContextMemoryRecord(
    ModelBase,
    TenantScopedMixin,
):  # pylint: disable=too-few-public-methods
    """Runtime structured memory record."""

    __tablename__ = "context_engine_context_memory_record"

    scope_partition: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    memory_type: Mapped[str] = mapped_column(CITEXT(64), nullable=False, index=True)
    memory_key: Mapped[str | None] = mapped_column(
        CITEXT(255), nullable=True, index=True
    )
    subject: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True, index=True)
    content: Mapped[dict | str | None] = mapped_column(JSONB, nullable=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    commit_token: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(memory_type)) > 0",
            name="ck_ctxeng_memory__memory_type",
        ),
        {"schema": _SCHEMA},
    )


class ContextCacheRecord(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """Runtime context cache record."""

    __tablename__ = "context_engine_context_cache_record"

    namespace: Mapped[str] = mapped_column(CITEXT(64), nullable=False, index=True)
    cache_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False)
    payload: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_hit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    hit_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "namespace",
            "cache_key",
            name="ux_ctxeng_cache__tenant_namespace_key",
        ),
        CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_ctxeng_cache__namespace",
        ),
        CheckConstraint(
            "length(btrim(cache_key)) > 0",
            name="ck_ctxeng_cache__cache_key",
        ),
        {"schema": _SCHEMA},
    )


class ContextCommitLedger(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """Runtime commit-token ledger."""

    __tablename__ = "context_engine_context_commit_ledger"

    scope_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False, index=True)
    commit_token: Mapped[str] = mapped_column(CITEXT(255), nullable=False)
    prepared_fingerprint: Mapped[str] = mapped_column(CITEXT(255), nullable=False)
    commit_state: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "commit_token",
            name="ux_ctxeng_commit_ledger__tenant_token",
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_commit_ledger__scope_key",
        ),
        CheckConstraint(
            "length(btrim(commit_token)) > 0",
            name="ck_ctxeng_commit_ledger__commit_token",
        ),
        CheckConstraint(
            "length(btrim(prepared_fingerprint)) > 0",
            name="ck_ctxeng_commit_ledger__prepared_fingerprint",
        ),
        CheckConstraint(
            "length(btrim(commit_state)) > 0",
            name="ck_ctxeng_commit_ledger__commit_state",
        ),
        {"schema": _SCHEMA},
    )


class ContextTrace(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """Runtime context trace record."""

    __tablename__ = "context_engine_context_trace"

    scope_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(
        CITEXT(255), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(CITEXT(64), nullable=False, index=True)
    selected_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dropped_items: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_trace__scope_key",
        ),
        CheckConstraint("length(btrim(stage)) > 0", name="ck_ctxeng_trace__stage"),
        Index(
            "ix_ctxeng_trace__tenant_scope_occurred",
            "tenant_id",
            "scope_key",
            "occurred_at",
        ),
        {"schema": _SCHEMA},
    )


metadata = MetaData()
for table in (
    ContextPolicy.__table__,
    ContextProfile.__table__,
    ContextContributorBinding.__table__,
    ContextSourceBinding.__table__,
    ContextTracePolicy.__table__,
    ContextStateSnapshot.__table__,
    ContextEventLog.__table__,
    ContextMemoryRecord.__table__,
    ContextCacheRecord.__table__,
    ContextCommitLedger.__table__,
    ContextTrace.__table__,
):
    table.to_metadata(metadata)
