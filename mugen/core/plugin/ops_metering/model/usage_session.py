"""Provides an ORM for usage session records."""

from __future__ import annotations

__all__ = ["UsageSession", "UsageSessionStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class UsageSessionStatus(str, enum.Enum):
    """Usage session lifecycle states."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


# pylint: disable=too-few-public-methods
class UsageSession(ModelBase, TenantScopedMixin):
    """An ORM for usage session state transitions and elapsed tracking."""

    __tablename__ = "ops_metering_usage_session"

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

    usage_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    tracked_namespace: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    tracked_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    tracked_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
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

    status: Mapped[str] = mapped_column(
        PGENUM(
            UsageSessionStatus,
            name="ops_metering_usage_session_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'idle'"),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    elapsed_seconds: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )

    last_actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
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
            name="fkx_ops_metering_usage_session__tenant_meter_definition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "meter_policy_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_policy.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_metering_meter_policy.id",
            ],
            name="fkx_ops_metering_usage_session__tenant_meter_policy",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(tracked_namespace)) > 0",
            name="ck_ops_metering_usage_session__tracked_namespace_nonempty",
        ),
        CheckConstraint(
            "tracked_ref IS NULL OR length(btrim(tracked_ref)) > 0",
            name="ck_ops_metering_usage_session__tracked_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "tracked_id IS NOT NULL OR tracked_ref IS NOT NULL",
            name="ck_ops_metering_usage_session__tracked_target_required",
        ),
        CheckConstraint(
            "elapsed_seconds >= 0",
            name="ck_ops_metering_usage_session__elapsed_seconds_nonnegative",
        ),
        CheckConstraint(
            "idempotency_key IS NULL OR length(btrim(idempotency_key)) > 0",
            name="ck_ops_metering_usage_session__idempotency_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_usage_session__tenant_id_id",
        ),
        Index(
            "ix_ops_metering_usage_session__tenant_tracking",
            "tenant_id",
            "tracked_namespace",
            "meter_definition_id",
            "tracked_id",
            "tracked_ref",
        ),
        Index(
            "ux_ops_metering_usage_session__tenant_idempotency_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=sa_text("idempotency_key IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"UsageSession(id={self.id!r})"
