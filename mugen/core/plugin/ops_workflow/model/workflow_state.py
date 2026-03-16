"""Provides an ORM for workflow version states."""

from __future__ import annotations

__all__ = ["WorkflowState"]

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_instance import WorkflowInstance
    from mugen.core.plugin.ops_workflow.model.workflow_transition import (
        WorkflowTransition,
    )
    from mugen.core.plugin.ops_workflow.model.workflow_version import WorkflowVersion


class WorkflowState(ModelBase, TenantScopedMixin):
    """An ORM for workflow version state declarations."""

    __tablename__ = "ops_workflow_workflow_state"

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

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
    )

    is_initial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    is_terminal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    version: Mapped["WorkflowVersion"] = relationship(  # type: ignore
        back_populates="states",
    )

    outgoing_transitions: Mapped[list["WorkflowTransition"]] = relationship(
        back_populates="from_state",
        foreign_keys="WorkflowTransition.from_state_id",
    )  # type: ignore

    incoming_transitions: Mapped[list["WorkflowTransition"]] = relationship(
        back_populates="to_state",
        foreign_keys="WorkflowTransition.to_state_id",
    )  # type: ignore

    current_instances: Mapped[list["WorkflowInstance"]] = relationship(  # type: ignore
        back_populates="current_state",
        foreign_keys="WorkflowInstance.current_state_id",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_version_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_version.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_version.id",
            ),
            name="fkx_ops_wf_state_tenant_version",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_wf_state_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_wf_state_name_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_state_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "workflow_version_id",
            "key",
            name="ux_ops_wf_state_tenant_version_key",
        ),
        Index(
            "ix_ops_wf_state_tenant_version_initial",
            "tenant_id",
            "workflow_version_id",
            "is_initial",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"WorkflowState(id={self.id!r})"
