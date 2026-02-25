"""Provides an ORM for append-only workflow timeline events."""

from __future__ import annotations

__all__ = ["WorkflowEvent", "WorkflowEventType"]

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
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

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_instance import WorkflowInstance
    from mugen.core.plugin.ops_workflow.model.workflow_task import WorkflowTask


class WorkflowEventType(str, enum.Enum):
    """Workflow timeline event categories."""

    CREATED = "created"
    STARTED = "started"
    ADVANCED = "advanced"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    TASK_ASSIGNED = "task_assigned"
    TASK_COMPLETED = "task_completed"
    CANCELLED = "cancelled"
    REPLAYED = "replayed"
    COMPENSATION_REQUESTED = "compensation_requested"
    COMPENSATION_PLANNED = "compensation_planned"
    COMPENSATION_FAILED = "compensation_failed"


class WorkflowEvent(ModelBase, TenantScopedMixin):
    """An ORM for append-only workflow timeline events."""

    __tablename__ = "ops_workflow_workflow_event"

    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    workflow_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    event_seq: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(
        PGENUM(
            WorkflowEventType,
            name="ops_workflow_event_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    from_state_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )

    to_state_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
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

    note: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    instance: Mapped["WorkflowInstance"] = relationship(  # type: ignore
        back_populates="events",
    )

    task: Mapped["WorkflowTask"] = relationship(  # type: ignore
        back_populates="events",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_event_tenant_instance",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "workflow_task_id"),
            (
                "mugen.ops_workflow_workflow_task.tenant_id",
                "mugen.ops_workflow_workflow_task.id",
            ),
            name="fkx_ops_wf_event_tenant_task",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_wf_event_note_nonempty",
        ),
        CheckConstraint(
            "event_seq IS NULL OR event_seq > 0",
            name="ck_ops_wf_event_event_seq_positive_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_event_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "workflow_instance_id",
            "event_seq",
            name="ux_ops_wf_event_tenant_instance_event_seq",
        ),
        Index(
            "ix_ops_wf_event_tenant_instance_occ",
            "tenant_id",
            "workflow_instance_id",
            "occurred_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkflowEvent(id={self.id!r})"
