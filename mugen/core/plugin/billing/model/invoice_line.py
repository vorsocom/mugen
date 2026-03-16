"""Provides an ORM for billing invoice lines."""

from __future__ import annotations

__all__ = ["InvoiceLine"]

from datetime import datetime
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class InvoiceLine(ModelBase, TenantScopedMixin):
    """An ORM for billing invoice lines."""

    __tablename__ = "billing_invoice_line"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    price_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    unit_amount: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    period_start: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    period_end: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    invoice: Mapped["Invoice"] = relationship(  # type: ignore
        back_populates="lines",
    )

    price: Mapped["Price | None"] = relationship(  # type: ignore
        back_populates="invoice_lines",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "invoice_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_invoice.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_invoice.id"),
            name="fkx_billing_invoice_line__tenant_invoice",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "price_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_price.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_price.id"),
            name="fkx_billing_invoice_line__tenant_price",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "quantity >= 0",
            name="ck_billing_invoice_line__quantity_nonneg",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_billing_invoice_line__amount_nonneg",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_invoice_line__tenant_id_id",
        ),
        Index(
            "ix_billing_invoice_line__tenant_invoice",
            "tenant_id",
            "invoice_id",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"InvoiceLine(id={self.id!r})"
