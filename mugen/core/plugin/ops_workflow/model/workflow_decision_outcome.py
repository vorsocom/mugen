"""Provides an ORM for workflow decision outcomes."""

from __future__ import annotations

__all__ = ["WorkflowDecisionOutcome"]

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_decision_request import (
        WorkflowDecisionRequest,
    )


class WorkflowDecisionOutcome(ModelBase, TenantScopedMixin):
    """An ORM for append-only decision resolution records."""

    __tablename__ = "ops_workflow_decision_outcome"

    decision_request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    resolver_actor_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    outcome_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    signature_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    decision_request: Mapped["WorkflowDecisionRequest"] = relationship(  # type: ignore
        back_populates="outcomes",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "decision_request_id"),
            (
                "mugen.ops_workflow_decision_request.tenant_id",
                "mugen.ops_workflow_decision_request.id",
            ),
            name="fkx_ops_wf_decision_outcome_tenant_request",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_decision_outcome_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "decision_request_id",
            name="ux_ops_wf_decision_outcome_tenant_request",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkflowDecisionOutcome(id={self.id!r})"
