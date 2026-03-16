"""Provides an ORM for aggregation job metadata."""

from __future__ import annotations

__all__ = ["AggregationJob", "AggregationJobStatus"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class AggregationJobStatus(str, enum.Enum):
    """Lifecycle status for aggregation jobs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# pylint: disable=too-few-public-methods
class AggregationJob(ModelBase, TenantScopedMixin):
    """An ORM for aggregation run metadata and idempotency tracking."""

    __tablename__ = "ops_reporting_aggregation_job"

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    bucket_minutes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("60"),
    )

    scope_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        server_default=sa_text("'__all__'"),
        index=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            AggregationJobStatus,
            name="ops_reporting_job_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        server_default=sa_text("'pending'"),
        index=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
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
            ["tenant_id", "metric_definition_id"],
            [
                f"{CORE_SCHEMA_TOKEN}.ops_reporting_metric_definition.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_reporting_metric_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_aggregation_job__tenant_metric_definition",
        ),
        CheckConstraint(
            "window_end > window_start",
            name="ck_ops_reporting_aggregation_job__window_bounds",
        ),
        CheckConstraint(
            "bucket_minutes > 0",
            name="ck_ops_reporting_aggregation_job__bucket_minutes_positive",
        ),
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_aggregation_job__scope_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_ops_reporting_aggregation_job__idempotency_key_nonempty",
        ),
        CheckConstraint(
            "error_message IS NULL OR length(btrim(error_message)) > 0",
            name="ck_ops_reporting_aggregation_job__error_message_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_aggregation_job__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="ux_ops_reporting_aggregation_job__tenant_idempotency_key",
        ),
        Index(
            "ix_ops_reporting_aggregation_job__tenant_metric_window",
            "tenant_id",
            "metric_definition_id",
            "window_start",
            "window_end",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"AggregationJob(id={self.id!r})"
