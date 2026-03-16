"""Provides an ORM for billing runs."""

from __future__ import annotations

__all__ = ["BillingRun", "BillingRunStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class BillingRunStatus(str, enum.Enum):
    """Billing run status enum."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


# pylint: disable=too-few-public-methods
class BillingRun(ModelBase, TenantScopedMixin):
    """An ORM for idempotent billing period runs."""

    __tablename__ = "billing_run"

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

    run_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    period_start: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    period_end: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            BillingRunStatus,
            name="billing_run_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'pending'"),
    )

    idempotency_key: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
        index=True,
    )

    started_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    external_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    account: Mapped["Account | None"] = relationship(  # type: ignore
        back_populates="billing_runs",
    )

    subscription: Mapped["Subscription | None"] = relationship(  # type: ignore
        back_populates="billing_runs",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_account.id"),
            name="fkx_billing_run__tenant_account",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "subscription_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_subscription.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_subscription.id"),
            name="fkx_billing_run__tenant_subscription",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(run_type)) > 0",
            name="ck_billing_run__run_type_nonempty",
        ),
        CheckConstraint(
            "period_end > period_start",
            name="ck_billing_run__period_bounds",
        ),
        CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_billing_run__idempotency_key_nonempty",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_run__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_run__tenant_id_id",
        ),
        Index(
            "ux_billing_run__tenant_idempotency_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
        ),
        Index(
            "ix_billing_run__tenant_run_type_period",
            "tenant_id",
            "run_type",
            "period_start",
        ),
        Index(
            "ux_billing_run__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"BillingRun(id={self.id!r})"
