"""Provides an ORM for billing accounts."""

__all__ = ["Account"]

from typing import TYPE_CHECKING, List

from sqlalchemy import (
    CheckConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN

if TYPE_CHECKING:
    from mugen.core.plugin.billing.model.entitlement_bucket import EntitlementBucket


# pylint: disable=too-few-public-methods
class Account(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for billing accounts."""

    __tablename__ = "billing_account"

    code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str] = mapped_column(
        CITEXT(256),
        nullable=False,
        index=True,
    )

    email: Mapped[str | None] = mapped_column(
        CITEXT(254),
        nullable=True,
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

    subscriptions: Mapped[List["Subscription"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    billing_runs: Mapped[List["BillingRun"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    invoices: Mapped[List["Invoice"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    credit_notes: Mapped[List["CreditNote"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    adjustments: Mapped[List["Adjustment"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    payments: Mapped[List["Payment"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    usage_events: Mapped[List["UsageEvent"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    ledger_entries: Mapped[List["LedgerEntry"]] = relationship(  # type: ignore
        back_populates="account",
        cascade="save-update, merge",
    )

    entitlement_buckets: Mapped[List["EntitlementBucket"]] = relationship(
        back_populates="account",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_billing_account__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_billing_account__display_name_nonempty",
        ),
        CheckConstraint(
            "email IS NULL OR length(btrim(email)) > 0",
            name="ck_billing_account__email_nonempty_if_set",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_account__external_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_account__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_account__tenant_id_id",
        ),
        Index(
            "ix_billing_account__tenant_code",
            "tenant_id",
            "code",
        ),
        Index(
            "ix_billing_account__tenant_external_ref",
            "tenant_id",
            "external_ref",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"Account(id={self.id!r})"
