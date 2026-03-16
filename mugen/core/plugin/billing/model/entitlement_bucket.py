"""Provides an ORM for billing entitlement buckets."""

from __future__ import annotations

__all__ = ["EntitlementBucket"]

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class EntitlementBucket(ModelBase, TenantScopedMixin):
    """An ORM for entitlement buckets (included usage pools)."""

    __tablename__ = "billing_entitlement_bucket"

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

    included_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    consumed_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    rollover_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
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
        back_populates="entitlement_buckets",
    )

    subscription: Mapped["Subscription | None"] = relationship(  # type: ignore
        back_populates="entitlement_buckets",
    )

    price: Mapped["Price | None"] = relationship(  # type: ignore
        back_populates="entitlement_buckets",
    )

    usage_allocations: Mapped[list["UsageAllocation"]] = relationship(  # type: ignore
        back_populates="entitlement_bucket",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_account.id"),
            name="fkx_billing_entitlement_bucket__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "subscription_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_subscription.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_subscription.id"),
            name="fkx_billing_entitlement_bucket__tenant_subscription",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "price_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_price.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_price.id"),
            name="fkx_billing_entitlement_bucket__tenant_price",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(meter_code)) > 0",
            name="ck_billing_entitlement_bucket__meter_code_nonempty",
        ),
        CheckConstraint(
            "period_end > period_start",
            name="ck_billing_entitlement_bucket__period_bounds",
        ),
        CheckConstraint(
            "included_quantity >= 0",
            name="ck_billing_entitlement_bucket__included_nonneg",
        ),
        CheckConstraint(
            "consumed_quantity >= 0",
            name="ck_billing_entitlement_bucket__consumed_nonneg",
        ),
        CheckConstraint(
            "rollover_quantity >= 0",
            name="ck_billing_entitlement_bucket__rollover_nonneg",
        ),
        CheckConstraint(
            "consumed_quantity <= (included_quantity + rollover_quantity)",
            name="ck_billing_entitlement_bucket__consumed_within_capacity",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_entitlement_bucket__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_entitlement_bucket__tenant_id_id",
        ),
        Index(
            "ix_billing_entitlement_bucket__tenant_account_meter_period",
            "tenant_id",
            "account_id",
            "meter_code",
            "period_start",
        ),
        Index(
            "ix_billing_entitlement_bucket__tenant_subscription_meter_period",
            "tenant_id",
            "subscription_id",
            "meter_code",
            "period_start",
        ),
        Index(
            "ux_billing_entitlement_bucket__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"EntitlementBucket(id={self.id!r})"
