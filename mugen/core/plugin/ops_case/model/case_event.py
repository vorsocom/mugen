"""Provides an ORM for case timeline and audit events."""

from __future__ import annotations

__all__ = ["CaseEvent", "CaseEventType"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class CaseEventType(str, enum.Enum):
    """Case event/timeline entry categories."""

    CREATED = "created"
    TRIAGED = "triaged"
    ASSIGNED = "assigned"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"
    CANCELLED = "cancelled"
    NOTE = "note"


# pylint: disable=too-few-public-methods
class CaseEvent(ModelBase, TenantScopedMixin):
    """An ORM for append-only case timeline events."""

    __tablename__ = "ops_case_case_event"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        PGENUM(
            CaseEventType,
            name="ops_case_event_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    status_from: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    status_to: Mapped[str | None] = mapped_column(
        String(64),
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

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    case: Mapped["Case"] = relationship(  # type: ignore
        back_populates="events",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "case_id"),
            ("mugen.ops_case_case.tenant_id", "mugen.ops_case_case.id"),
            name="fkx_ops_case_case_event__tenant_case",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_case_case_event__note_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case_event__tenant_id_id",
        ),
        Index(
            "ix_ops_case_case_event__tenant_case_occurred",
            "tenant_id",
            "case_id",
            "occurred_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"CaseEvent(id={self.id!r})"

