"""Provides an ORM for usage record entries."""

from __future__ import annotations

__all__ = ["UsageRecord", "UsageRecordStatus"]

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


class UsageRecordStatus(str, enum.Enum):
    """Usage record lifecycle states."""

    RECORDED = "recorded"
    RATED = "rated"
    VOID = "void"


# pylint: disable=too-few-public-methods
class UsageRecord(ModelBase, TenantScopedMixin):
    """An ORM for immutable usage records plus rating and void metadata."""

    __tablename__ = "ops_metering_usage_record"

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

    usage_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    rated_usage_id: Mapped[uuid.UUID | None] = mapped_column(
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

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    measured_minutes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    measured_units: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    measured_tasks: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            UsageRecordStatus,
            name="ops_metering_usage_record_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'recorded'"),
    )

    rated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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

    idempotency_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    external_ref: Mapped[str | None] = mapped_column(
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
            ["tenant_id", "meter_definition_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_definition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_definition.id",
            ],
            name="fkx_ops_metering_usage_record__tenant_meter_definition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "meter_policy_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_policy.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_policy.id",
            ],
            name="fkx_ops_metering_usage_record__tenant_meter_policy",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "usage_session_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_usage_session.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_usage_session.id",
            ],
            name="fkx_ops_metering_usage_record__tenant_usage_session",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "measured_minutes >= 0",
            name="ck_ops_metering_usage_record__measured_minutes_nonnegative",
        ),
        CheckConstraint(
            "measured_units >= 0",
            name="ck_ops_metering_usage_record__measured_units_nonnegative",
        ),
        CheckConstraint(
            "measured_tasks >= 0",
            name="ck_ops_metering_usage_record__measured_tasks_nonnegative",
        ),
        CheckConstraint(
            "(measured_minutes + measured_units + measured_tasks) > 0",
            name="ck_ops_metering_usage_record__measured_positive_required",
        ),
        CheckConstraint(
            "void_reason IS NULL OR length(btrim(void_reason)) > 0",
            name="ck_ops_metering_usage_record__void_reason_nonempty_if_set",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR length(btrim(idempotency_key)) > 0",
            name="ck_ops_metering_usage_record__idempotency_nonempty_if_set",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_ops_metering_usage_record__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_usage_record__tenant_id_id",
        ),
        Index(
            "ix_ops_metering_usage_record__tenant_meter_occurred",
            "tenant_id",
            "meter_definition_id",
            "occurred_at",
        ),
        Index(
            "ux_ops_metering_usage_record__tenant_idempotency_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ux_ops_metering_usage_record__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        Index(
            "ux_ops_metering_usage_record__tenant_usage_session",
            "tenant_id",
            "usage_session_id",
            unique=True,
            postgresql_where=sa_text("usage_session_id IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"UsageRecord(id={self.id!r})"
