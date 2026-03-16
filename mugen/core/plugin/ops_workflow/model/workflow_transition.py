"""Provides an ORM for workflow state transitions."""

from __future__ import annotations

__all__ = ["WorkflowTransition"]

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_instance import WorkflowInstance
    from mugen.core.plugin.ops_workflow.model.workflow_state import WorkflowState
    from mugen.core.plugin.ops_workflow.model.workflow_task import WorkflowTask
    from mugen.core.plugin.ops_workflow.model.workflow_version import WorkflowVersion


class WorkflowTransition(ModelBase, TenantScopedMixin):
    """An ORM for deterministic workflow transitions."""

    __tablename__ = "ops_workflow_workflow_transition"

    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    key: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    from_state_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    to_state_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    auto_assign_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    auto_assign_queue: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    compensation_json: Mapped[dict | list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    version: Mapped["WorkflowVersion"] = relationship(  # type: ignore
        back_populates="transitions",
    )

    from_state: Mapped["WorkflowState"] = relationship(  # type: ignore
        back_populates="outgoing_transitions",
        foreign_keys=[from_state_id],
    )

    to_state: Mapped["WorkflowState"] = relationship(  # type: ignore
        back_populates="incoming_transitions",
        foreign_keys=[to_state_id],
    )

    pending_instances: Mapped[list["WorkflowInstance"]] = relationship(  # type: ignore
        back_populates="pending_transition",
        foreign_keys="WorkflowInstance.pending_transition_id",
    )

    tasks: Mapped[list["WorkflowTask"]] = relationship(  # type: ignore
        back_populates="transition",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_version_id"),
            (
                "mugen.ops_workflow_workflow_version.tenant_id",
                "mugen.ops_workflow_workflow_version.id",
            ),
            name="fkx_ops_wf_transition_tenant_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "from_state_id"),
            (
                "mugen.ops_workflow_workflow_state.tenant_id",
                "mugen.ops_workflow_workflow_state.id",
            ),
            name="fkx_ops_wf_transition_tenant_from_state",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "to_state_id"),
            (
                "mugen.ops_workflow_workflow_state.tenant_id",
                "mugen.ops_workflow_workflow_state.id",
            ),
            name="fkx_ops_wf_transition_tenant_to_state",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_wf_transition_key_nonempty",
        ),
        CheckConstraint(
            "from_state_id <> to_state_id",
            name="ck_ops_wf_transition_non_self_loop",
        ),
        CheckConstraint(
            "auto_assign_queue IS NULL OR length(btrim(auto_assign_queue)) > 0",
            name="ck_ops_wf_transition_auto_queue_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_transition_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "workflow_version_id",
            "key",
            name="ux_ops_wf_transition_tenant_version_key",
        ),
        Index(
            "ix_ops_wf_transition_tenant_from_state",
            "tenant_id",
            "from_state_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkflowTransition(id={self.id!r})"
