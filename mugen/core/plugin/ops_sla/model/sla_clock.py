"""Provides an ORM for SLA clock tracking records."""

from __future__ import annotations

__all__ = ["SlaClock", "SlaClockStatus"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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


class SlaClockStatus(str, enum.Enum):
    """SLA clock lifecycle states."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    BREACHED = "breached"


# pylint: disable=too-few-public-methods
class SlaClock(ModelBase, TenantScopedMixin):
    """An ORM for SLA elapsed-time tracking and deadline state."""

    __tablename__ = "ops_sla_clock"

    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.ops_sla_policy.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    calendar_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.ops_sla_calendar.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    target_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.ops_sla_target.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    clock_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.ops_sla_clock_definition.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    tracked_namespace: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    tracked_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    tracked_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    metric: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    priority: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )

    severity: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            SlaClockStatus,
            name="ops_sla_clock_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("idle"),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    elapsed_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    is_breached: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    breach_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    warned_offsets_json: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(tracked_namespace)) > 0",
            name="ck_ops_sla_clock__tracked_namespace_nonempty",
        ),
        CheckConstraint(
            "tracked_ref IS NULL OR length(btrim(tracked_ref)) > 0",
            name="ck_ops_sla_clock__tracked_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "tracked_id IS NOT NULL OR tracked_ref IS NOT NULL",
            name="ck_ops_sla_clock__tracked_target_required",
        ),
        CheckConstraint(
            "length(btrim(metric)) > 0",
            name="ck_ops_sla_clock__metric_nonempty",
        ),
        CheckConstraint(
            "priority IS NULL OR length(btrim(priority)) > 0",
            name="ck_ops_sla_clock__priority_nonempty_if_set",
        ),
        CheckConstraint(
            "severity IS NULL OR length(btrim(severity)) > 0",
            name="ck_ops_sla_clock__severity_nonempty_if_set",
        ),
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_sla_clock__trace_id_nonempty_if_set",
        ),
        CheckConstraint(
            "elapsed_seconds >= 0",
            name="ck_ops_sla_clock__elapsed_seconds_nonnegative",
        ),
        CheckConstraint(
            "breach_count >= 0",
            name="ck_ops_sla_clock__breach_count_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_clock__tenant_id_id",
        ),
        Index(
            "ix_ops_sla_clock__tenant_status_deadline",
            "tenant_id",
            "status",
            "deadline_at",
        ),
        Index(
            "ix_ops_sla_clock__tenant_tracking",
            "tenant_id",
            "tracked_namespace",
            "metric",
            "tracked_id",
            "tracked_ref",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SlaClock(id={self.id!r})"
