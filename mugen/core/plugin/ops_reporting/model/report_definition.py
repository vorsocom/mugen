"""Provides an ORM for report definition records."""

from __future__ import annotations

__all__ = ["ReportDefinition"]

from sqlalchemy import Boolean, CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class ReportDefinition(ModelBase, TenantScopedMixin):
    """An ORM for generic KPI report definitions."""

    __tablename__ = "ops_reporting_report_definition"

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

    description: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    metric_codes: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    filters_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    group_by_json: Mapped[list | None] = mapped_column(
        JSONB,
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
            name="ck_ops_reporting_report_definition__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_reporting_report_definition__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_reporting_report_definition__description_nonempty_if_set",
        ),
        CheckConstraint(
            "metric_codes IS NULL OR jsonb_typeof(metric_codes) = 'array'",
            name="ck_ops_reporting_report_definition__metric_codes_array",
        ),
        CheckConstraint(
            "group_by_json IS NULL OR jsonb_typeof(group_by_json) = 'array'",
            name="ck_ops_reporting_report_definition__group_by_json_array",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_report_definition__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_reporting_report_definition__tenant_code",
        ),
        Index(
            "ix_ops_reporting_report_definition__tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ReportDefinition(id={self.id!r})"
