"""Provides an ORM for workflow definition versions."""

from __future__ import annotations

__all__ = ["WorkflowVersion", "WorkflowVersionStatus"]

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
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.ops_workflow.model.workflow_definition import (
        WorkflowDefinition,
    )
    from mugen.core.plugin.ops_workflow.model.workflow_instance import WorkflowInstance
    from mugen.core.plugin.ops_workflow.model.workflow_state import WorkflowState
    from mugen.core.plugin.ops_workflow.model.workflow_transition import (
        WorkflowTransition,
    )


class WorkflowVersionStatus(str, enum.Enum):
    """Workflow version lifecycle states."""

    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class WorkflowVersion(ModelBase, TenantScopedMixin):
    """An ORM for workflow definition versions."""

    __tablename__ = "ops_workflow_workflow_version"

    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    version_number: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            WorkflowVersionStatus,
            name="ops_workflow_version_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'draft'"),
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    definition: Mapped["WorkflowDefinition"] = relationship(  # type: ignore
        back_populates="versions",
    )

    states: Mapped[list["WorkflowState"]] = relationship(  # type: ignore
        back_populates="version",
        cascade="save-update, merge",
    )

    transitions: Mapped[list["WorkflowTransition"]] = relationship(  # type: ignore
        back_populates="version",
        cascade="save-update, merge",
    )

    instances: Mapped[list["WorkflowInstance"]] = relationship(  # type: ignore
        back_populates="version",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "workflow_definition_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_definition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_workflow_workflow_definition.id",
            ),
            name="fkx_ops_wf_ver_tenant_definition",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "version_number > 0",
            name="ck_ops_wf_ver_version_number_positive",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_ver_tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "workflow_definition_id",
            "version_number",
            name="ux_ops_wf_ver_tenant_def_version",
        ),
        Index(
            "ix_ops_wf_ver_tenant_def_status",
            "tenant_id",
            "workflow_definition_id",
            "status",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"WorkflowVersion(id={self.id!r})"
