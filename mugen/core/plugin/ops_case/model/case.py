"""Provides an ORM for operations cases."""

from __future__ import annotations

__all__ = ["Case", "CasePriority", "CaseSeverity", "CaseStatus"]

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.ops_case.model.case_assignment import CaseAssignment
    from mugen.core.plugin.ops_case.model.case_event import CaseEvent
    from mugen.core.plugin.ops_case.model.case_link import CaseLink


class CaseStatus(str, enum.Enum):
    """Case lifecycle states."""

    NEW = "new"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    WAITING_EXTERNAL = "waiting_external"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CasePriority(str, enum.Enum):
    """Case priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class CaseSeverity(str, enum.Enum):
    """Case severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# pylint: disable=too-few-public-methods
class Case(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for operations case records."""

    __tablename__ = "ops_case_case"

    case_number: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(
        CITEXT(256),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            CaseStatus,
            name="ops_case_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'new'"),
    )

    priority: Mapped[str] = mapped_column(
        PGENUM(
            CasePriority,
            name="ops_case_priority",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'medium'"),
    )

    severity: Mapped[str] = mapped_column(
        PGENUM(
            CaseSeverity,
            name="ops_case_severity",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'medium'"),
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    sla_target_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    triaged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    escalation_level: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    is_escalated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    escalated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    resolution_summary: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    events: Mapped[list["CaseEvent"]] = relationship(  # type: ignore
        back_populates="case",
        cascade="save-update, merge",
    )

    assignments: Mapped[list["CaseAssignment"]] = relationship(  # type: ignore
        back_populates="case",
        cascade="save-update, merge",
    )

    links: Mapped[list["CaseLink"]] = relationship(  # type: ignore
        back_populates="case",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(case_number)) > 0",
            name="ck_ops_case_case__case_number_nonempty",
        ),
        CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_ops_case_case__title_nonempty",
        ),
        CheckConstraint(
            "queue_name IS NULL OR length(btrim(queue_name)) > 0",
            name="ck_ops_case_case__queue_name_nonempty_if_set",
        ),
        CheckConstraint(
            "resolution_summary IS NULL OR length(btrim(resolution_summary)) > 0",
            name="ck_ops_case_case__resolution_summary_nonempty_if_set",
        ),
        CheckConstraint(
            "cancellation_reason IS NULL OR length(btrim(cancellation_reason)) > 0",
            name="ck_ops_case_case__cancellation_reason_nonempty_if_set",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="ck_ops_case_case__escalation_level_nonnegative",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_case_case__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "case_number",
            name="ux_ops_case_case__tenant_case_number",
        ),
        Index(
            "ix_ops_case_case__tenant_status_priority",
            "tenant_id",
            "status",
            "priority",
        ),
        Index(
            "ix_ops_case_case__tenant_owner_queue",
            "tenant_id",
            "owner_user_id",
            "queue_name",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Case(id={self.id!r})"

