"""Provides an ORM for workflow action-key replay and hash-mismatch checks."""

from __future__ import annotations

__all__ = ["WorkflowActionDedup"]

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class WorkflowActionDedup(ModelBase, TenantScopedMixin):
    """An ORM for per-instance action-key replay-safe responses."""

    __tablename__ = "ops_workflow_action_dedup"

    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    action_name: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    client_action_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    request_hash: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
    )

    response_code: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    response_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_action_dedup_tenant_instance",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(action_name)) > 0",
            name="ck_ops_wf_action_dedup_action_nonempty",
        ),
        CheckConstraint(
            "length(btrim(client_action_key)) > 0",
            name="ck_ops_wf_action_dedup_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(request_hash)) > 0",
            name="ck_ops_wf_action_dedup_hash_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_action_dedup_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "workflow_instance_id",
            "action_name",
            "client_action_key",
            name="ux_ops_wf_action_dedup_instance_action_key",
        ),
        Index(
            "ix_ops_wf_action_dedup_tenant_instance_completed",
            "tenant_id",
            "workflow_instance_id",
            "completed_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"WorkflowActionDedup(id={self.id!r})"
