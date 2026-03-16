"""Provides an ORM for metering policy records."""

from __future__ import annotations

__all__ = ["MeterPolicy", "MeterRoundingMode"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class MeterRoundingMode(str, enum.Enum):
    """Supported metering rounding modes."""

    NONE = "none"
    UP = "up"
    DOWN = "down"
    NEAREST = "nearest"


# pylint: disable=too-few-public-methods
class MeterPolicy(ModelBase, TenantScopedMixin):
    """An ORM for metering policy definitions."""

    __tablename__ = "ops_metering_meter_policy"

    meter_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

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

    cap_minutes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    cap_units: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    cap_tasks: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    multiplier_bps: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("10000"),
    )

    rounding_mode: Mapped[str] = mapped_column(
        PGENUM(
            MeterRoundingMode,
            name="ops_metering_rounding_mode",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'none'"),
    )

    rounding_step: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    billable_window_minutes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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
            ["tenant_id", "meter_definition_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_definition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_definition.id",
            ],
            name="fkx_ops_metering_meter_policy__tenant_meter_definition",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_metering_meter_policy__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_metering_meter_policy__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_metering_meter_policy__description_nonempty_if_set",
        ),
        CheckConstraint(
            "cap_minutes IS NULL OR cap_minutes >= 0",
            name="ck_ops_metering_meter_policy__cap_minutes_nonnegative",
        ),
        CheckConstraint(
            "cap_units IS NULL OR cap_units >= 0",
            name="ck_ops_metering_meter_policy__cap_units_nonnegative",
        ),
        CheckConstraint(
            "cap_tasks IS NULL OR cap_tasks >= 0",
            name="ck_ops_metering_meter_policy__cap_tasks_nonnegative",
        ),
        CheckConstraint(
            "multiplier_bps >= 0",
            name="ck_ops_metering_meter_policy__multiplier_bps_nonnegative",
        ),
        CheckConstraint(
            "rounding_step > 0",
            name="ck_ops_metering_meter_policy__rounding_step_positive",
        ),
        CheckConstraint(
            "billable_window_minutes IS NULL OR billable_window_minutes >= 0",
            name="ck_ops_metering_meter_policy__billable_window_nonnegative",
        ),
        CheckConstraint(
            (
                "effective_to IS NULL OR effective_from IS NULL OR"
                " effective_to >= effective_from"
            ),
            name="ck_ops_metering_meter_policy__effective_window_bounds",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_meter_policy__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "meter_definition_id",
            "code",
            name="ux_ops_metering_meter_policy__tenant_meter_code",
        ),
        Index(
            "ix_ops_metering_meter_policy__tenant_meter_active",
            "tenant_id",
            "meter_definition_id",
            "is_active",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"MeterPolicy(id={self.id!r})"
