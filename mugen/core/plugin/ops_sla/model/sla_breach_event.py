"""Provides an ORM for append-only SLA breach events."""

from __future__ import annotations

__all__ = ["SlaBreachEvent", "SlaBreachEventType"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class SlaBreachEventType(str, enum.Enum):
    """SLA breach event categories."""

    BREACHED = "breached"
    ESCALATED = "escalated"
    ACKNOWLEDGED = "acknowledged"


# pylint: disable=too-few-public-methods
class SlaBreachEvent(ModelBase, TenantScopedMixin):
    """An ORM for append-only breach/escalation markers."""

    __tablename__ = "ops_sla_breach_event"

    clock_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        PGENUM(
            SlaBreachEventType,
            name="ops_sla_breach_event_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
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
        nullable=True,
        index=True,
    )

    escalation_level: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id"],
            [f"{CORE_SCHEMA_TOKEN}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_breach_event__tenant_id__admin_tenant",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{CORE_SCHEMA_TOKEN}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_breach_event__actor_uid__admin_user",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "clock_id"],
            [f"{CORE_SCHEMA_TOKEN}.ops_sla_clock.tenant_id", f"{CORE_SCHEMA_TOKEN}.ops_sla_clock.id"],
            ondelete="CASCADE",
            name="fkx_ops_sla_breach_event__tenant_clock",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_ops_sla_breach_event__reason_nonempty_if_set",
        ),
        CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_sla_breach_event__note_nonempty_if_set",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="ck_ops_sla_breach_event__escalation_level_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_breach_event__tenant_id_id",
        ),
        Index(
            "ix_ops_sla_breach_event__tenant_clock_occurred",
            "tenant_id",
            "clock_id",
            "occurred_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SlaBreachEvent(id={self.id!r})"
