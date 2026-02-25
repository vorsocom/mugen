"""Provides an ORM for policy decision log entries."""

from __future__ import annotations

__all__ = ["PolicyDecisionLog", "PolicyDecision", "PolicyOutcome"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy import UniqueConstraint, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class PolicyDecision(str, enum.Enum):
    """Policy decision values."""

    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"
    REVIEW = "review"


class PolicyOutcome(str, enum.Enum):
    """Policy evaluation outcome values."""

    APPLIED = "applied"
    BLOCKED = "blocked"
    DEFERRED = "deferred"


# pylint: disable=too-few-public-methods
class PolicyDecisionLog(ModelBase, TenantScopedMixin):
    """An ORM for append-only policy decision outcomes."""

    __tablename__ = "ops_governance_policy_decision_log"

    policy_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    policy_key: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    policy_version: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    subject_namespace: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    subject_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    decision: Mapped[str] = mapped_column(
        PGENUM(
            PolicyDecision,
            name="ops_governance_policy_decision",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    outcome: Mapped[str] = mapped_column(
        PGENUM(
            PolicyOutcome,
            name="ops_governance_policy_outcome",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'applied'"),
    )

    reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    evaluator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    request_context: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    actor_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    input_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    decision_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "policy_definition_id"),
            (
                "mugen.ops_governance_policy_definition.tenant_id",
                "mugen.ops_governance_policy_definition.id",
            ),
            name="fkx_ops_gov_policy_decision_log__tenant_policy_definition",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(subject_namespace)) > 0",
            name="ck_ops_gov_policy_decision_log__subject_namespace_nonempty",
        ),
        CheckConstraint(
            "subject_ref IS NULL OR length(btrim(subject_ref)) > 0",
            name="ck_ops_gov_policy_decision_log__subject_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_ops_gov_policy_decision_log__reason_nonempty_if_set",
        ),
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_gov_policy_decision_log__trace_id_nonempty_if_set",
        ),
        CheckConstraint(
            "policy_key IS NULL OR length(btrim(policy_key)) > 0",
            name="ck_ops_gov_policy_decision_log__policy_key_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_policy_decision_log__tenant_id_id",
        ),
        Index(
            "ix_ops_gov_policy_decision_log__tenant_policy_eval",
            "tenant_id",
            "policy_definition_id",
            "evaluated_at",
        ),
        Index(
            "ix_ops_gov_policy_decision_log__tenant_trace",
            "tenant_id",
            "trace_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"PolicyDecisionLog(id={self.id!r})"
