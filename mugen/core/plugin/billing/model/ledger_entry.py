"""Provides an ORM for billing ledger entries."""

from __future__ import annotations

__all__ = ["LedgerEntry", "LedgerDirection"]

from datetime import datetime
import enum
import uuid

from sqlalchemy import (
    BigInteger,
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


class LedgerDirection(str, enum.Enum):
    """Ledger entry direction enum."""

    DEBIT = "debit"
    CREDIT = "credit"


# pylint: disable=too-few-public-methods
class LedgerEntry(ModelBase, TenantScopedMixin):
    """An ORM for billing ledger entries."""

    __tablename__ = "billing_ledger_entry"

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

    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    direction: Mapped[str] = mapped_column(
        PGENUM(
            LedgerDirection,
            name="billing_ledger_direction",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'debit'"),
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

    occurred_at: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
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
        back_populates="ledger_entries",
    )

    invoice: Mapped["Invoice | None"] = relationship(  # type: ignore
        back_populates="ledger_entries",
    )

    payment: Mapped["Payment | None"] = relationship(  # type: ignore
        back_populates="ledger_entries",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_account.id"),
            name="fkx_billing_ledger_entry__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "invoice_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_invoice.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_invoice.id"),
            name="fkx_billing_ledger_entry__tenant_invoice",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "payment_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_payment.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_payment.id"),
            name="fkx_billing_ledger_entry__tenant_payment",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_ledger_entry__currency_len3",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_billing_ledger_entry__amount_nonneg",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_ledger_entry__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_ledger_entry__tenant_id_id",
        ),
        Index(
            "ix_billing_ledger_entry__tenant_account_occurred",
            "tenant_id",
            "account_id",
            "occurred_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"LedgerEntry(id={self.id!r})"
