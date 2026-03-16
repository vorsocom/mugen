"""Provides an ORM for billing payments."""

from __future__ import annotations

__all__ = ["Payment", "PaymentStatus"]

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


class PaymentStatus(str, enum.Enum):
    """Payment status enum."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


# pylint: disable=too-few-public-methods
class Payment(ModelBase, TenantScopedMixin):
    """An ORM for billing payments."""

    __tablename__ = "billing_payment"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            PaymentStatus,
            name="billing_payment_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'pending'"),
    )

    currency: Mapped[str] = mapped_column(
        CITEXT(3),
        nullable=False,
        index=True,
    )

    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    provider: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    external_ref: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
        index=True,
    )

    received_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    failed_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    account: Mapped["Account"] = relationship(  # type: ignore
        back_populates="payments",
    )

    invoice: Mapped["Invoice | None"] = relationship(  # type: ignore
        back_populates="payments",
    )

    ledger_entries: Mapped[list["LedgerEntry"]] = relationship(  # type: ignore
        back_populates="payment",
        cascade="save-update, merge",
    )

    allocations: Mapped[list["PaymentAllocation"]] = relationship(  # type: ignore
        back_populates="payment",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            ("mugen.billing_account.tenant_id", "mugen.billing_account.id"),
            name="fkx_billing_payment__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "invoice_id"),
            ("mugen.billing_invoice.tenant_id", "mugen.billing_invoice.id"),
            name="fkx_billing_payment__tenant_invoice",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_payment__currency_len3",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_billing_payment__amount_nonneg",
        ),
        CheckConstraint(
            "provider IS NULL OR length(btrim(provider)) > 0",
            name="ck_billing_payment__provider_nonempty_if_set",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_payment__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_payment__tenant_id_id",
        ),
        Index(
            "ix_billing_payment__tenant_account",
            "tenant_id",
            "account_id",
        ),
        Index(
            "ux_billing_payment__tenant_external_ref",
            "tenant_id",
            "provider",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Payment(id={self.id!r})"
