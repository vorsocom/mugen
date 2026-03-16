"""Provides an ORM for billing usage events."""

from __future__ import annotations

__all__ = ["UsageEvent", "UsageEventStatus"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class UsageEventStatus(str, enum.Enum):
    """Usage event status enum."""

    RECORDED = "recorded"
    VOID = "void"


# pylint: disable=too-few-public-methods
class UsageEvent(ModelBase, TenantScopedMixin):
    """An ORM for billing usage events."""

    __tablename__ = "billing_usage_event"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
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

    occurred_at: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            UsageEventStatus,
            name="billing_usage_event_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'recorded'"),
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

    account: Mapped["Account"] = relationship(  # type: ignore
        back_populates="usage_events",
    )

    subscription: Mapped["Subscription | None"] = relationship(  # type: ignore
        back_populates="usage_events",
    )

    price: Mapped["Price | None"] = relationship(  # type: ignore
        back_populates="usage_events",
    )

    usage_allocations: Mapped[list["UsageAllocation"]] = relationship(  # type: ignore
        back_populates="usage_event",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_account.id"),
            name="fkx_billing_usage_event__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "subscription_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_subscription.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_subscription.id"),
            name="fkx_billing_usage_event__tenant_subscription",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "price_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_price.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_price.id"),
            name="fkx_billing_usage_event__tenant_price",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_billing_usage_event__quantity_nonneg",
        ),
        CheckConstraint(
            "length(btrim(meter_code)) > 0",
            name="ck_billing_usage_event__meter_code_nonempty",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_usage_event__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_usage_event__tenant_id_id",
        ),
        Index(
            "ix_billing_usage_event__tenant_account_occurred",
            "tenant_id",
            "account_id",
            "occurred_at",
        ),
        Index(
            "ix_billing_usage_event__tenant_account_meter_occurred",
            "tenant_id",
            "account_id",
            "meter_code",
            "occurred_at",
        ),
        Index(
            "ux_billing_usage_event__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"UsageEvent(id={self.id!r})"
