"""Provides an ORM for workflow runtime instances."""

from __future__ import annotations

__all__ = ["WorkflowInstance", "WorkflowInstanceStatus"]

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

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
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_definition import (
        WorkflowDefinition,
    )
    from mugen.core.plugin.ops_workflow.model.workflow_event import WorkflowEvent
    from mugen.core.plugin.ops_workflow.model.workflow_state import WorkflowState
    from mugen.core.plugin.ops_workflow.model.workflow_task import WorkflowTask
    from mugen.core.plugin.ops_workflow.model.workflow_transition import (
        WorkflowTransition,
    )
    from mugen.core.plugin.ops_workflow.model.workflow_version import WorkflowVersion


class WorkflowInstanceStatus(str, enum.Enum):
    """Workflow instance runtime states."""

    DRAFT = "draft"
    ACTIVE = "active"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowInstance(ModelBase, TenantScopedMixin):
    """An ORM for tenant-scoped workflow runtime instances."""

    __tablename__ = "ops_workflow_workflow_instance"

    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    current_state_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    pending_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    pending_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    external_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            WorkflowInstanceStatus,
            name="ops_workflow_instance_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'draft'"),
    )

    subject_namespace: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
    )

    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    subject_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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

    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    cancel_reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    definition: Mapped["WorkflowDefinition"] = relationship(  # type: ignore
        back_populates="instances",
    )

    version: Mapped["WorkflowVersion"] = relationship(  # type: ignore
        back_populates="instances",
    )

    current_state: Mapped["WorkflowState"] = relationship(  # type: ignore
        back_populates="current_instances",
        foreign_keys=[current_state_id],
    )

    pending_transition: Mapped["WorkflowTransition"] = relationship(  # type: ignore
        back_populates="pending_instances",
        foreign_keys=[pending_transition_id],
    )

    tasks: Mapped[list["WorkflowTask"]] = relationship(  # type: ignore
        back_populates="instance",
        cascade="save-update, merge",
    )

    events: Mapped[list["WorkflowEvent"]] = relationship(  # type: ignore
        back_populates="instance",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_definition_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_definition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_definition.id",
            ),
            name="fkx_ops_wf_instance_tenant_definition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "workflow_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_version.id",
            ),
            name="fkx_ops_wf_instance_tenant_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "current_state_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_state.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_state.id",
            ),
            name="fkx_ops_wf_instance_tenant_current_state",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "pending_transition_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_transition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_transition.id",
            ),
            name="fkx_ops_wf_instance_tenant_pending_transition",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "title IS NULL OR length(btrim(title)) > 0",
            name="ck_ops_wf_instance_title_nonempty",
        ),
        CheckConstraint(
            "subject_namespace IS NULL OR length(btrim(subject_namespace)) > 0",
            name="ck_ops_wf_instance_subject_ns_nonempty",
        ),
        CheckConstraint(
            "subject_ref IS NULL OR length(btrim(subject_ref)) > 0",
            name="ck_ops_wf_instance_subject_ref_nonempty",
        ),
        CheckConstraint(
            "cancel_reason IS NULL OR length(btrim(cancel_reason)) > 0",
            name="ck_ops_wf_instance_cancel_reason_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_instance_tenant_id_id",
        ),
        Index(
            "ix_ops_wf_instance_tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_ops_wf_instance_tenant_version_state",
            "tenant_id",
            "workflow_version_id",
            "current_state_id",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"WorkflowInstance(id={self.id!r})"
