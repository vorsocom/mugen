"""Provides an ORM for workflow decision requests."""

from __future__ import annotations

__all__ = ["WorkflowDecisionRequest", "WorkflowDecisionRequestStatus"]

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_decision_outcome import (
        WorkflowDecisionOutcome,
    )


class WorkflowDecisionRequestStatus(str, enum.Enum):
    """Workflow decision request lifecycle states."""

    OPEN = "open"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class WorkflowDecisionRequest(ModelBase, TenantScopedMixin):
    """An ORM for workflow-linked approval/decision requests."""

    __tablename__ = "ops_workflow_decision_request"

    trace_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    template_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            WorkflowDecisionRequestStatus,
            name="ops_workflow_decision_request_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'open'"),
    )

    requester_actor_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    assigned_to_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    options_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    context_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    workflow_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    outcomes: Mapped[list["WorkflowDecisionOutcome"]] = relationship(  # type: ignore
        back_populates="decision_request",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_decision_request_tenant_instance",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "workflow_task_id"),
            (
                "mugen.ops_workflow_workflow_task.tenant_id",
                "mugen.ops_workflow_workflow_task.id",
            ),
            name="fkx_ops_wf_decision_request_tenant_task",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_wf_decision_request_trace_nonempty",
        ),
        CheckConstraint(
            "length(btrim(template_key)) > 0",
            name="ck_ops_wf_decision_request_template_key_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_decision_request_tenant_id_id",
        ),
        Index(
            "ix_ops_wf_decision_request_tenant_status_due_at",
            "tenant_id",
            "status",
            "due_at",
        ),
        Index(
            "ix_ops_wf_decision_request_tenant_trace",
            "tenant_id",
            "trace_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkflowDecisionRequest(id={self.id!r})"
