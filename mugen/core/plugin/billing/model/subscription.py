"""Provides an ORM for billing subscriptions."""

from __future__ import annotations

__all__ = ["Subscription", "SubscriptionStatus"]

from datetime import datetime
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
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
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.billing.model.entitlement_bucket import EntitlementBucket


class SubscriptionStatus(str, enum.Enum):
    """Subscription status enum."""

    ACTIVE = "active"
    TRIALING = "trialing"
    PAUSED = "paused"
    CANCELED = "canceled"
    ENDED = "ended"


# pylint: disable=too-few-public-methods
class Subscription(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for billing subscriptions."""

    __tablename__ = "billing_subscription"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    price_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            SubscriptionStatus,
            name="billing_subscription_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'active'"),
    )

    started_at: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    current_period_start: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    current_period_end: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    cancel_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    canceled_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    ended_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
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
        back_populates="subscriptions",
    )

    price: Mapped["Price"] = relationship(  # type: ignore
        back_populates="subscriptions",
    )

    invoices: Mapped[list["Invoice"]] = relationship(  # type: ignore
        back_populates="subscription",
        cascade="save-update, merge",
    )

    usage_events: Mapped[list["UsageEvent"]] = relationship(  # type: ignore
        back_populates="subscription",
        cascade="save-update, merge",
    )

    billing_runs: Mapped[list["BillingRun"]] = relationship(  # type: ignore
        back_populates="subscription",
        cascade="save-update, merge",
    )

    entitlement_buckets: Mapped[list["EntitlementBucket"]] = relationship(
        back_populates="subscription",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            ("mugen.billing_account.tenant_id", "mugen.billing_account.id"),
            name="fkx_billing_subscription__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "price_id"),
            ("mugen.billing_price.tenant_id", "mugen.billing_price.id"),
            name="fkx_billing_subscription__tenant_price",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_subscription__external_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_subscription__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_subscription__tenant_id_id",
        ),
        Index(
            "ix_billing_subscription__tenant_account",
            "tenant_id",
            "account_id",
        ),
        Index(
            "ix_billing_subscription__tenant_price",
            "tenant_id",
            "price_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Subscription(id={self.id!r})"
