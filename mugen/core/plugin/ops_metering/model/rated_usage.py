"""Provides an ORM for rated usage entries."""

from __future__ import annotations

__all__ = ["RatedUsage", "RatedUsageStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
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


class RatedUsageStatus(str, enum.Enum):
    """Rated usage lifecycle states."""

    RATED = "rated"
    VOID = "void"


# pylint: disable=too-few-public-methods
class RatedUsage(ModelBase, TenantScopedMixin):
    """An ORM for normalized rated usage entries prior to billing handoff."""

    __tablename__ = "ops_metering_rated_usage"

    usage_record_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    meter_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    meter_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    price_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    meter_code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    unit: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
    )

    measured_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    capped_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    multiplier_bps: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("10000"),
    )

    billable_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    rated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            RatedUsageStatus,
            name="ops_metering_rated_usage_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'rated'"),
    )

    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    void_reason: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    billing_usage_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    billing_external_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "usage_record_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_usage_record.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_usage_record.id",
            ],
            name="fkx_ops_metering_rated_usage__tenant_usage_record",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "meter_definition_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_definition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_definition.id",
            ],
            name="fkx_ops_metering_rated_usage__tenant_meter_definition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "meter_policy_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_policy.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_policy.id",
            ],
            name="fkx_ops_metering_rated_usage__tenant_meter_policy",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(meter_code)) > 0",
            name="ck_ops_metering_rated_usage__meter_code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_ops_metering_rated_usage__unit_nonempty",
        ),
        CheckConstraint(
            "measured_quantity >= 0",
            name="ck_ops_metering_rated_usage__measured_quantity_nonnegative",
        ),
        CheckConstraint(
            "capped_quantity >= 0",
            name="ck_ops_metering_rated_usage__capped_quantity_nonnegative",
        ),
        CheckConstraint(
            "multiplier_bps >= 0",
            name="ck_ops_metering_rated_usage__multiplier_bps_nonnegative",
        ),
        CheckConstraint(
            "billable_quantity >= 0",
            name="ck_ops_metering_rated_usage__billable_quantity_nonnegative",
        ),
        CheckConstraint(
            "void_reason IS NULL OR length(btrim(void_reason)) > 0",
            name="ck_ops_metering_rated_usage__void_reason_nonempty_if_set",
        ),
        CheckConstraint(
            (
                "billing_external_ref IS NULL OR"
                " length(btrim(billing_external_ref)) > 0"
            ),
            name="ck_ops_metering_rated_usage__billing_ext_ref_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_rated_usage__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "usage_record_id",
            name="ux_ops_metering_rated_usage__tenant_usage_record",
        ),
        Index(
            "ix_ops_metering_rated_usage__tenant_meter_occurred",
            "tenant_id",
            "meter_code",
            "occurred_at",
        ),
        Index(
            "ux_ops_metering_rated_usage__tenant_billing_external_ref",
            "tenant_id",
            "billing_external_ref",
            unique=True,
            postgresql_where=sa_text("billing_external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"RatedUsage(id={self.id!r})"
