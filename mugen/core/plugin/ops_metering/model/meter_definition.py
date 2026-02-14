"""Provides an ORM for metering definition records."""

from __future__ import annotations

__all__ = ["MeterDefinition", "MeterUnit", "MeterAggregationMode"]

import enum

from sqlalchemy import Boolean, CheckConstraint, Index, String, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class MeterUnit(str, enum.Enum):
    """Supported canonical metering units."""

    MINUTE = "minute"
    UNIT = "unit"
    TASK = "task"


class MeterAggregationMode(str, enum.Enum):
    """Supported aggregation modes for measured usage."""

    SUM = "sum"
    MAX = "max"
    LATEST = "latest"


# pylint: disable=too-few-public-methods
class MeterDefinition(ModelBase, TenantScopedMixin):
    """An ORM for metering definitions."""

    __tablename__ = "ops_metering_meter_definition"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    unit: Mapped[str] = mapped_column(
        PGENUM(
            MeterUnit,
            name="ops_metering_meter_unit",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'unit'"),
    )

    aggregation_mode: Mapped[str] = mapped_column(
        PGENUM(
            MeterAggregationMode,
            name="ops_metering_aggregation_mode",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'sum'"),
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
            name="ck_ops_metering_meter_definition__code_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_metering_meter_definition__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_meter_definition__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_metering_meter_definition__tenant_code",
        ),
        Index(
            "ix_ops_metering_meter_definition__tenant_active",
            "tenant_id",
            "is_active",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"MeterDefinition(id={self.id!r})"
