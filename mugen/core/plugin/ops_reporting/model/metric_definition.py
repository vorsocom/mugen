"""Provides an ORM for metric definition records."""

from __future__ import annotations

__all__ = ["MetricDefinition", "MetricFormulaType"]

import enum

from sqlalchemy import Boolean, CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class MetricFormulaType(str, enum.Enum):
    """Supported formula types for metric aggregation."""

    COUNT_ROWS = "count_rows"
    SUM_COLUMN = "sum_column"
    AVG_COLUMN = "avg_column"
    MIN_COLUMN = "min_column"
    MAX_COLUMN = "max_column"


# pylint: disable=too-few-public-methods
class MetricDefinition(ModelBase, TenantScopedMixin):
    """An ORM for generic metric definitions."""

    __tablename__ = "ops_reporting_metric_definition"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    formula_type: Mapped[str] = mapped_column(
        PGENUM(
            MetricFormulaType,
            name="ops_reporting_formula_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'count_rows'"),
    )

    source_table: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    source_time_column: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    source_value_column: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    scope_column: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    source_filter: Mapped[dict | None] = mapped_column(
        JSONB,
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
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_reporting_metric_definition__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_reporting_metric_definition__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(source_table)) > 0",
            name="ck_ops_reporting_metric_definition__source_table_nonempty",
        ),
        CheckConstraint(
            "source_time_column IS NULL OR length(btrim(source_time_column)) > 0",
            name="ck_ops_reporting_metric_definition__source_time_nonempty_if_set",
        ),
        CheckConstraint(
            "source_value_column IS NULL OR length(btrim(source_value_column)) > 0",
            name="ck_ops_reporting_metric_def__source_value_nonempty_if_set",
        ),
        CheckConstraint(
            "scope_column IS NULL OR length(btrim(scope_column)) > 0",
            name="ck_ops_reporting_metric_def__scope_column_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "formula_type = 'count_rows' OR"
                " source_value_column IS NOT NULL"
            ),
            name="ck_ops_reporting_metric_definition__value_column_required",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_reporting_metric_definition__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_metric_definition__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_reporting_metric_definition__tenant_code",
        ),
        Index(
            "ix_ops_reporting_metric_definition__tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"MetricDefinition(id={self.id!r})"
