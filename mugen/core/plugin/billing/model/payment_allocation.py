"""Provides an ORM for billing payment allocations."""

__all__ = ["PaymentAllocation"]

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
class PaymentAllocation(ModelBase, TenantScopedMixin):
    """An ORM for payment allocations."""

    __tablename__ = "billing_payment_allocation"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    allocated_at: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
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

    payment: Mapped["Payment"] = relationship(  # type: ignore
        back_populates="allocations",
    )

    invoice: Mapped["Invoice"] = relationship(  # type: ignore
        back_populates="allocations",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "payment_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_payment.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_payment.id"),
            name="fkx_billing_payment_allocation__tenant_payment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "invoice_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_invoice.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_invoice.id"),
            name="fkx_billing_payment_allocation__tenant_invoice",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "amount > 0",
            name="ck_billing_payment_allocation__amount_positive",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_payment_allocation__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_payment_allocation__tenant_id_id",
        ),
        Index(
            "ix_billing_payment_allocation__tenant_payment",
            "tenant_id",
            "payment_id",
        ),
        Index(
            "ix_billing_payment_allocation__tenant_invoice",
            "tenant_id",
            "invoice_id",
        ),
        Index(
            "ux_billing_payment_allocation__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"PaymentAllocation(id={self.id!r})"
