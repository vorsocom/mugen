"""Provides an ORM for workflow tasks and handoffs."""

from __future__ import annotations

__all__ = ["WorkflowTask", "WorkflowTaskKind", "WorkflowTaskStatus"]

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
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_event import WorkflowEvent
    from mugen.core.plugin.ops_workflow.model.workflow_instance import WorkflowInstance
    from mugen.core.plugin.ops_workflow.model.workflow_transition import (
        WorkflowTransition,
    )


class WorkflowTaskKind(str, enum.Enum):
    """Workflow task categories."""

    APPROVAL = "approval"
    WORK_ITEM = "work_item"


class WorkflowTaskStatus(str, enum.Enum):
    """Workflow task lifecycle states."""

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class WorkflowTask(ModelBase, TenantScopedMixin):
    """An ORM for workflow tasks used in approvals and handoffs."""

    __tablename__ = "ops_workflow_workflow_task"

    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    workflow_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    task_kind: Mapped[str] = mapped_column(
        PGENUM(
            WorkflowTaskKind,
            name="ops_workflow_task_kind",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'work_item'"),
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            WorkflowTaskStatus,
            name="ops_workflow_task_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'open'"),
    )

    title: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
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

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    handoff_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    outcome: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    payload: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    instance: Mapped["WorkflowInstance"] = relationship(  # type: ignore
        back_populates="tasks",
    )

    transition: Mapped["WorkflowTransition"] = relationship(  # type: ignore
        back_populates="tasks",
    )

    events: Mapped[list["WorkflowEvent"]] = relationship(  # type: ignore
        back_populates="task",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_task_tenant_instance",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "workflow_transition_id"),
            (
                "mugen.ops_workflow_workflow_transition.tenant_id",
                "mugen.ops_workflow_workflow_transition.id",
            ),
            name="fkx_ops_wf_task_tenant_transition",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_ops_wf_task_title_nonempty",
        ),
        CheckConstraint(
            "queue_name IS NULL OR length(btrim(queue_name)) > 0",
            name="ck_ops_wf_task_queue_nonempty",
        ),
        CheckConstraint(
            "outcome IS NULL OR length(btrim(outcome)) > 0",
            name="ck_ops_wf_task_outcome_nonempty",
        ),
        CheckConstraint(
            "handoff_count >= 0",
            name="ck_ops_wf_task_handoff_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_task_tenant_id_id",
        ),
        Index(
            "ix_ops_wf_task_tenant_instance_status",
            "tenant_id",
            "workflow_instance_id",
            "status",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkflowTask(id={self.id!r})"
