"""Provides an ORM for lifecycle action log records."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, CheckConstraint, Index, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class LifecycleActionLog(ModelBase, TenantScopedMixin):
    """Append-only lifecycle orchestration action log."""

    __tablename__ = "ops_governance_lifecycle_action_log"

    resource_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    action_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    outcome: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    dry_run: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    details: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_gov_lifecycle_log__resource_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(action_type)) > 0",
            name="ck_ops_gov_lifecycle_log__action_type_nonempty",
        ),
        CheckConstraint(
            "length(btrim(outcome)) > 0",
            name="ck_ops_gov_lifecycle_log__outcome_nonempty",
        ),
        CheckConstraint(
            "correlation_id IS NULL OR length(btrim(correlation_id)) > 0",
            name="ck_ops_gov_lifecycle_log__correlation_nonempty_if_set",
        ),
        Index(
            "ix_ops_gov_lifecycle_log__tenant_resource_created",
            "tenant_id",
            "resource_type",
            "resource_id",
            "created_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"LifecycleActionLog(id={self.id!r})"
