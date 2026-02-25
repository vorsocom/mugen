"""Provides an ORM for warning/breach events emitted by SLA tick processing."""

from __future__ import annotations

__all__ = ["SlaClockEvent", "SlaClockEventType"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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


class SlaClockEventType(str, enum.Enum):
    """Clock event categories emitted during SLA tick processing."""

    WARNED = "warned"
    BREACHED = "breached"


class SlaClockEvent(ModelBase, TenantScopedMixin):
    """An ORM for append-only clock warning and breach markers."""

    __tablename__ = "ops_sla_clock_event"

    clock_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    clock_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        PGENUM(
            SlaClockEventType,
            name="ops_sla_clock_event_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    warned_offset_seconds: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    payload_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "clock_id"),
            (
                "mugen.ops_sla_clock.tenant_id",
                "mugen.ops_sla_clock.id",
            ),
            name="fkx_ops_sla_clock_event__tenant_clock",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "clock_definition_id"),
            (
                "mugen.ops_sla_clock_definition.tenant_id",
                "mugen.ops_sla_clock_definition.id",
            ),
            name="fkx_ops_sla_clock_event__tenant_clock_definition",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "warned_offset_seconds IS NULL OR warned_offset_seconds >= 0",
            name="ck_ops_sla_clock_event__warned_offset_nonnegative_if_set",
        ),
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_sla_clock_event__trace_id_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_clock_event__tenant_id_id",
        ),
        Index(
            "ix_ops_sla_clock_event__tenant_clock_occ",
            "tenant_id",
            "clock_id",
            "occurred_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"SlaClockEvent(id={self.id!r})"
