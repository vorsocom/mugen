"""Provides an ORM for workflow definitions."""

from __future__ import annotations

__all__ = ["WorkflowDefinition"]

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_instance import WorkflowInstance
    from mugen.core.plugin.ops_workflow.model.workflow_version import WorkflowVersion


class WorkflowDefinition(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for tenant-scoped workflow definitions."""

    __tablename__ = "ops_workflow_workflow_definition"

    key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String(2048),
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

    versions: Mapped[list["WorkflowVersion"]] = relationship(  # type: ignore
        back_populates="definition",
        cascade="save-update, merge",
    )

    instances: Mapped[list["WorkflowInstance"]] = relationship(  # type: ignore
        back_populates="definition",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_wf_def_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_wf_def_name_nonempty",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_wf_def_soft_delete_consistent",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_def_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "key",
            name="ux_ops_wf_def_tenant_key",
        ),
        Index(
            "ix_ops_wf_def_tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"WorkflowDefinition(id={self.id!r})"
