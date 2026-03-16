"""Provides an ORM for unified SLA clock-definition metadata."""

from __future__ import annotations

__all__ = ["SlaClockDefinition"]

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class SlaClockDefinition(ModelBase, TenantScopedMixin):
    """An ORM for declarative SLA clock-definition rows."""

    __tablename__ = "ops_sla_clock_definition"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        CITEXT(1024),
        nullable=True,
    )

    metric: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    target_minutes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    warn_offsets_json: Mapped[list | None] = mapped_column(
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
            name="ck_ops_sla_clock_definition__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_clock_definition__name_nonempty",
        ),
        CheckConstraint(
            "length(btrim(metric)) > 0",
            name="ck_ops_sla_clock_definition__metric_nonempty",
        ),
        CheckConstraint(
            "target_minutes > 0",
            name="ck_ops_sla_clock_definition__target_minutes_positive",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_clock_definition__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_sla_clock_definition__tenant_code",
        ),
        Index(
            "ix_ops_sla_clock_definition__tenant_metric_active",
            "tenant_id",
            "metric",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SlaClockDefinition(id={self.id!r})"
