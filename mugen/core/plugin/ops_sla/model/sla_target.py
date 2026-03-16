"""Provides an ORM for SLA target definitions."""

__all__ = ["SlaTarget"]

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class SlaTarget(ModelBase, TenantScopedMixin):
    """An ORM for SLA targets by metric and severity/priority bucket."""

    __tablename__ = "ops_sla_target"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "mugen.ops_sla_policy.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    metric: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    priority: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )

    severity: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )

    target_minutes: Mapped[int] = mapped_column(
        nullable=False,
    )

    warn_before_minutes: Mapped[int] = mapped_column(
        nullable=False,
        server_default=sa_text("0"),
    )

    auto_breach: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(metric)) > 0",
            name="ck_ops_sla_target__metric_nonempty",
        ),
        CheckConstraint(
            "priority IS NULL OR length(btrim(priority)) > 0",
            name="ck_ops_sla_target__priority_nonempty_if_set",
        ),
        CheckConstraint(
            "severity IS NULL OR length(btrim(severity)) > 0",
            name="ck_ops_sla_target__severity_nonempty_if_set",
        ),
        CheckConstraint(
            "target_minutes > 0",
            name="ck_ops_sla_target__target_minutes_positive",
        ),
        CheckConstraint(
            "warn_before_minutes >= 0",
            name="ck_ops_sla_target__warn_before_minutes_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_target__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "policy_id",
            "metric",
            "priority",
            "severity",
            name="ux_ops_sla_target__policy_metric_bucket",
        ),
        Index(
            "ix_ops_sla_target__tenant_policy_metric",
            "tenant_id",
            "policy_id",
            "metric",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"SlaTarget(id={self.id!r})"
