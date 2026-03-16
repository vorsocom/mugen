"""Provides an ORM for auditable escalation execution run records."""

from __future__ import annotations

__all__ = ["SlaEscalationRun", "SlaEscalationRunStatus"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class SlaEscalationRunStatus(str, enum.Enum):
    """Aggregate outcome status for escalation-run planning/execution records."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    NOOP = "noop"


class SlaEscalationRun(ModelBase, TenantScopedMixin):
    """An ORM for append-only escalation run logs with per-action diagnostics."""

    __tablename__ = "ops_sla_escalation_run"

    escalation_policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    clock_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    clock_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            SlaEscalationRunStatus,
            name="ops_sla_escalation_run_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'noop'"),
    )

    trigger_event_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
    )

    results_json: Mapped[list | dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    executed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "escalation_policy_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_sla_escalation_policy.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_sla_escalation_policy.id",
            ),
            name="fkx_ops_sla_escalation_run__tenant_policy",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "clock_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_sla_clock.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_sla_clock.id",
            ),
            name="fkx_ops_sla_escalation_run__tenant_clock",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "clock_event_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_sla_clock_event.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_sla_clock_event.id",
            ),
            name="fkx_ops_sla_escalation_run__tenant_clock_event",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_sla_escalation_run__trace_id_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_escalation_run__tenant_id_id",
        ),
        Index(
            "ix_ops_sla_escalation_run__tenant_policy_exec",
            "tenant_id",
            "escalation_policy_id",
            "executed_at",
        ),
        Index(
            "ix_ops_sla_escalation_run__tenant_status_exec",
            "tenant_id",
            "status",
            "executed_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SlaEscalationRun(id={self.id!r})"
