"""Provides an ORM for append-only entitlement adjustments."""

__all__ = ["EntitlementAdjustment"]

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class EntitlementAdjustment(ModelBase, TenantScopedMixin):
    """An append-only, audited entitlement capacity adjustment."""

    __tablename__ = "billing_entitlement_adjustment"

    bucket_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    account_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )
    quantity_delta: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    capacity_after: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "bucket_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.billing_entitlement_bucket.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.billing_entitlement_bucket.id",
            ),
            name="fkx_billing_entitlement_adjustment__tenant_bucket",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.billing_account.id",
            ),
            name="fkx_billing_entitlement_adjustment__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "subscription_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.billing_subscription.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.billing_subscription.id",
            ),
            name="fkx_billing_entitlement_adjustment__tenant_subscription",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "quantity_delta <> 0",
            name="ck_billing_entitlement_adjustment__delta_nonzero",
        ),
        CheckConstraint(
            "adjustment_after = adjustment_before + quantity_delta",
            name="ck_billing_entitlement_adjustment__adjustment_math",
        ),
        CheckConstraint(
            "capacity_after >= 0",
            name="ck_billing_entitlement_adjustment__capacity_nonnegative",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0",
            name="ck_billing_entitlement_adjustment__reason_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_entitlement_adjustment__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="ux_billing_entitlement_adjustment__tenant_idempotency",
        ),
        Index(
            "ix_billing_entitlement_adjustment__tenant_bucket_occurred",
            "tenant_id",
            "bucket_id",
            "occurred_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )
