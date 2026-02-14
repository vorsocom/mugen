"""Provides an ORM for case assignment history."""

from __future__ import annotations

__all__ = ["CaseAssignment"]

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class CaseAssignment(ModelBase, TenantScopedMixin):
    """An ORM for case assignment snapshots over time."""

    __tablename__ = "ops_case_case_assignment"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    queue_name: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    unassigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    case: Mapped["Case"] = relationship(  # type: ignore
        back_populates="assignments",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "case_id"),
            ("mugen.ops_case_case.tenant_id", "mugen.ops_case_case.id"),
            name="fkx_ops_case_case_assignment__tenant_case",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "queue_name IS NULL OR length(btrim(queue_name)) > 0",
            name="ck_ops_case_case_assignment__queue_name_nonempty_if_set",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_ops_case_case_assignment__reason_nonempty_if_set",
        ),
        CheckConstraint(
            "NOT (is_active AND unassigned_at IS NOT NULL)",
            name="ck_ops_case_case_assignment__active_without_unassigned_at",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case_assignment__tenant_id_id",
        ),
        Index(
            "ix_ops_case_case_assignment__tenant_case_assigned",
            "tenant_id",
            "case_id",
            "assigned_at",
        ),
        Index(
            "ix_ops_case_case_assignment__tenant_case_active",
            "tenant_id",
            "case_id",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"CaseAssignment(id={self.id!r})"

