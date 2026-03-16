"""Provides an ORM for aggregated metric series values."""

from __future__ import annotations

__all__ = ["MetricSeries"]

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class MetricSeries(ModelBase, TenantScopedMixin):
    """An ORM for time-bucketed metric values."""

    __tablename__ = "ops_reporting_metric_series"

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    bucket_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    bucket_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    scope_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        server_default=sa_text("'__all__'"),
        index=True,
    )

    value_numeric: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    source_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    aggregation_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
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
            name="fkx_ops_reporting_metric_series__tenant_metric_definition",
        ),
        CheckConstraint(
            "bucket_end > bucket_start",
            name="ck_ops_reporting_metric_series__bucket_window_bounds",
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_metric_series__scope_key_nonempty",
        ),
        CheckConstraint(
            "source_count >= 0",
            name="ck_ops_reporting_metric_series__source_count_nonnegative",
        ),
        CheckConstraint(
            "length(btrim(aggregation_key)) > 0",
            name="ck_ops_reporting_metric_series__aggregation_key_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_metric_series__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "aggregation_key",
            name="ux_ops_reporting_metric_series__tenant_aggregation_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "metric_definition_id",
            "bucket_start",
            "bucket_end",
            "scope_key",
            name="ux_ops_reporting_metric_series__tenant_bucket_scope",
        ),
        Index(
            "ix_ops_reporting_metric_series__tenant_metric_bucket",
            "tenant_id",
            "metric_definition_id",
            "bucket_start",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"MetricSeries(id={self.id!r})"
