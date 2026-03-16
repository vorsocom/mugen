"""Provides an ORM for billing adjustments."""

from __future__ import annotations

__all__ = ["Adjustment", "AdjustmentKind"]

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


class AdjustmentKind(str, enum.Enum):
    """Adjustment kind enum."""

    CREDIT = "credit"
    DEBIT = "debit"


# pylint: disable=too-few-public-methods
class Adjustment(ModelBase, TenantScopedMixin):
    """An ORM for billing adjustments."""

    __tablename__ = "billing_adjustment"

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

    credit_note_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    kind: Mapped[str] = mapped_column(
        PGENUM(
            AdjustmentKind,
            name="billing_adjustment_kind",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'credit'"),
    )

    currency: Mapped[str] = mapped_column(
        CITEXT(3),
        nullable=False,
        index=True,
    )

    amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    occurred_at: Mapped["datetime"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    reason: Mapped[str | None] = mapped_column(
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
        back_populates="adjustments",
    )

    invoice: Mapped["Invoice | None"] = relationship(  # type: ignore
        back_populates="adjustments",
    )

    credit_note: Mapped["CreditNote | None"] = relationship(  # type: ignore
        back_populates="adjustments",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_account.id"),
            name="fkx_billing_adjustment__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "invoice_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_invoice.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_invoice.id"),
            name="fkx_billing_adjustment__tenant_invoice",
            ondelete="SET NULL",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "credit_note_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_credit_note.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_credit_note.id"),
            name="fkx_billing_adjustment__tenant_credit_note",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_adjustment__currency_len3",
        ),
        CheckConstraint(
            "amount >= 0",
            name="ck_billing_adjustment__amount_nonneg",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_billing_adjustment__reason_nonempty_if_set",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_adjustment__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_adjustment__tenant_id_id",
        ),
        Index(
            "ix_billing_adjustment__tenant_account_occurred",
            "tenant_id",
            "account_id",
            "occurred_at",
        ),
        Index(
            "ix_billing_adjustment__tenant_invoice",
            "tenant_id",
            "invoice_id",
        ),
        Index(
            "ix_billing_adjustment__tenant_credit_note",
            "tenant_id",
            "credit_note_id",
        ),
        Index(
            "ux_billing_adjustment__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"Adjustment(id={self.id!r})"
