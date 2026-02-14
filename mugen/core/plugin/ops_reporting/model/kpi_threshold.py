"""Provides an ORM for KPI threshold records."""

from __future__ import annotations

__all__ = ["KpiThreshold"]

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class KpiThreshold(ModelBase, TenantScopedMixin):
    """An ORM for KPI target bands and threshold boundaries."""

    __tablename__ = "ops_reporting_kpi_threshold"

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    scope_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        server_default=sa_text("'__all__'"),
        index=True,
    )

    target_value: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    warn_low: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    warn_high: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    critical_low: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    critical_high: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(1024),
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

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "metric_definition_id"],
            [
                "mugen.ops_reporting_metric_definition.tenant_id",
                "mugen.ops_reporting_metric_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_kpi_threshold__tenant_metric_definition",
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_kpi_threshold__scope_key_nonempty",
        ),
        CheckConstraint(
            "warn_low IS NULL OR warn_high IS NULL OR warn_low <= warn_high",
            name="ck_ops_reporting_kpi_threshold__warn_bounds",
        ),
        CheckConstraint(
            (
                "critical_low IS NULL OR critical_high IS NULL OR"
                " critical_low <= critical_high"
            ),
            name="ck_ops_reporting_kpi_threshold__critical_bounds",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_reporting_kpi_threshold__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_kpi_threshold__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "metric_definition_id",
            "scope_key",
            name="ux_ops_reporting_kpi_threshold__tenant_metric_scope",
        ),
        Index(
            "ix_ops_reporting_kpi_threshold__tenant_metric_active",
            "tenant_id",
            "metric_definition_id",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"KpiThreshold(id={self.id!r})"
