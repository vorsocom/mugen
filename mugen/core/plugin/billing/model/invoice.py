"""Provides an ORM for billing invoices."""

from __future__ import annotations

__all__ = ["Invoice", "InvoiceStatus"]

from datetime import datetime
import enum
import uuid
from typing import List

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
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class InvoiceStatus(str, enum.Enum):
    """Invoice status enum."""

    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


# pylint: disable=too-few-public-methods
class Invoice(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for billing invoices."""

    __tablename__ = "billing_invoice"

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

    status: Mapped[str] = mapped_column(
        PGENUM(
            InvoiceStatus,
            name="billing_invoice_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'draft'"),
    )

    number: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    currency: Mapped[str] = mapped_column(
        CITEXT(3),
        nullable=False,
        index=True,
    )

    subtotal_amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    tax_amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    total_amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    amount_due: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    issued_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    due_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    paid_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    voided_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    account: Mapped["Account"] = relationship(  # type: ignore
        back_populates="invoices",
    )

    subscription: Mapped["Subscription | None"] = relationship(  # type: ignore
        back_populates="invoices",
    )

    lines: Mapped[List["InvoiceLine"]] = relationship(  # type: ignore
        back_populates="invoice",
        cascade="save-update, merge",
    )

    credit_notes: Mapped[List["CreditNote"]] = relationship(  # type: ignore
        back_populates="invoice",
        cascade="save-update, merge",
    )

    adjustments: Mapped[List["Adjustment"]] = relationship(  # type: ignore
        back_populates="invoice",
        cascade="save-update, merge",
    )

    payments: Mapped[List["Payment"]] = relationship(  # type: ignore
        back_populates="invoice",
        cascade="save-update, merge",
    )

    allocations: Mapped[List["PaymentAllocation"]] = relationship(  # type: ignore
        back_populates="invoice",
        cascade="save-update, merge",
    )

    ledger_entries: Mapped[List["LedgerEntry"]] = relationship(  # type: ignore
        back_populates="invoice",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            ("mugen.billing_account.tenant_id", "mugen.billing_account.id"),
            name="fkx_billing_invoice__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "subscription_id"),
            ("mugen.billing_subscription.tenant_id", "mugen.billing_subscription.id"),
            name="fkx_billing_invoice__tenant_subscription",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_invoice__currency_len3",
        ),
        CheckConstraint(
            "number IS NULL OR length(btrim(number)) > 0",
            name="ck_billing_invoice__number_nonempty_if_set",
        ),
        CheckConstraint(
            "subtotal_amount >= 0",
            name="ck_billing_invoice__subtotal_nonneg",
        ),
        CheckConstraint(
            "tax_amount >= 0",
            name="ck_billing_invoice__tax_nonneg",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_billing_invoice__total_nonneg",
        ),
        CheckConstraint(
            "amount_due >= 0",
            name="ck_billing_invoice__amount_due_nonneg",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_invoice__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_invoice__tenant_id_id",
        ),
        Index(
            "ix_billing_invoice__tenant_account",
            "tenant_id",
            "account_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Invoice(id={self.id!r})"
