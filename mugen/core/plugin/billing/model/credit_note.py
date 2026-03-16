"""Provides an ORM for billing credit notes."""

from __future__ import annotations

__all__ = ["CreditNote", "CreditNoteStatus"]

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


class CreditNoteStatus(str, enum.Enum):
    """Credit note status enum."""

    DRAFT = "draft"
    ISSUED = "issued"
    VOID = "void"


# pylint: disable=too-few-public-methods
class CreditNote(ModelBase, TenantScopedMixin):
    """An ORM for billing credit notes."""

    __tablename__ = "billing_credit_note"

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
            CreditNoteStatus,
            name="billing_credit_note_status",
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

    total_amount: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    issued_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
        DateTime(timezone=True),
        nullable=True,
    )

    voided_at: Mapped["datetime | None"] = mapped_column(  # type: ignore
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
        back_populates="credit_notes",
    )

    invoice: Mapped["Invoice | None"] = relationship(  # type: ignore
        back_populates="credit_notes",
    )

    adjustments: Mapped[list["Adjustment"]] = relationship(  # type: ignore
        back_populates="credit_note",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "account_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_account.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_account.id"),
            name="fkx_billing_credit_note__tenant_account",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "invoice_id"),
            (f"{CORE_SCHEMA_TOKEN}.billing_invoice.tenant_id", f"{CORE_SCHEMA_TOKEN}.billing_invoice.id"),
            name="fkx_billing_credit_note__tenant_invoice",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_credit_note__currency_len3",
        ),
        CheckConstraint(
            "number IS NULL OR length(btrim(number)) > 0",
            name="ck_billing_credit_note__number_nonempty_if_set",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_billing_credit_note__total_nonneg",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_credit_note__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_credit_note__tenant_id_id",
        ),
        Index(
            "ix_billing_credit_note__tenant_account",
            "tenant_id",
            "account_id",
        ),
        Index(
            "ix_billing_credit_note__tenant_invoice",
            "tenant_id",
            "invoice_id",
        ),
        Index(
            "ux_billing_credit_note__tenant_number",
            "tenant_id",
            "number",
            unique=True,
            postgresql_where=sa_text("number IS NOT NULL"),
        ),
        Index(
            "ux_billing_credit_note__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"CreditNote(id={self.id!r})"
