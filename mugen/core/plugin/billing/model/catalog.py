"""Provides ORMs for global billing catalog definitions."""

from __future__ import annotations

__all__ = [
    "CurrencyDefinition",
    "DiscountDefinition",
    "InvoiceTemplate",
    "MeterDefinition",
    "PaymentTerm",
    "PriceEntitlement",
    "RunDefinition",
    "TaxCode",
    "TaxRate",
]

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class _GlobalDefinitionMixin:
    """Shared columns for activatable global definitions."""

    code: Mapped[str] = mapped_column(CITEXT(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(CITEXT(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


# pylint: disable=too-few-public-methods
class MeterDefinition(ModelBase):
    """A canonical global meter definition."""

    __tablename__ = "billing_meter_definition"

    code: Mapped[str] = mapped_column(CITEXT(64), nullable=False, unique=True)
    unit: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)
    aggregation_mode: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        index=True,
        server_default=sa_text("'sum'"),
    )
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_billing_meter_definition__code_nonempty",
        ),
        CheckConstraint(
            "unit IN ('minute', 'unit', 'task')",
            name="ck_billing_meter_definition__unit",
        ),
        CheckConstraint(
            "aggregation_mode IN ('sum', 'max', 'latest')",
            name="ck_billing_meter_definition__aggregation_mode",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_billing_meter_definition__description_nonempty_if_set",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class PriceEntitlement(ModelBase, SoftDeleteMixin):
    """An included-usage rule owned by a recurring Price."""

    __tablename__ = "billing_price_entitlement"

    price_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.billing_price.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    meter_definition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.billing_meter_definition.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    included_quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rollover_policy: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'none'"),
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "included_quantity >= 0",
            name="ck_billing_price_entitlement__included_nonnegative",
        ),
        CheckConstraint(
            "rollover_policy = 'none'",
            name="ck_billing_price_entitlement__rollover_policy",
        ),
        Index(
            "ux_billing_price_entitlement__active_price_meter",
            "price_id",
            "meter_definition_id",
            unique=True,
            postgresql_where=sa_text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_price_entitlement__archive_actor",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class RunDefinition(ModelBase, _GlobalDefinitionMixin):
    """A reusable global billing-run cadence definition."""

    __tablename__ = "billing_run_definition"

    frequency: Mapped[str] = mapped_column(CITEXT(32), nullable=False)
    interval_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=sa_text("1"),
    )
    timezone: Mapped[str] = mapped_column(CITEXT(128), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "frequency IN ('manual', 'daily', 'weekly', 'monthly', 'yearly')",
            name="ck_billing_run_definition__frequency",
        ),
        CheckConstraint(
            "interval_count > 0",
            name="ck_billing_run_definition__interval_positive",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class CurrencyDefinition(ModelBase):
    """An ISO 4217 currency that may be enabled for billing."""

    __tablename__ = "billing_currency_definition"

    code: Mapped[str] = mapped_column(CITEXT(3), nullable=False, unique=True)
    numeric_code: Mapped[str] = mapped_column(String(3), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(CITEXT(128), nullable=False)
    minor_unit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint("length(code) = 3", name="ck_billing_currency__code_len3"),
        CheckConstraint(
            "numeric_code ~ '^[0-9]{3}$'",
            name="ck_billing_currency__numeric_code",
        ),
        CheckConstraint(
            "minor_unit IS NULL OR minor_unit BETWEEN 0 AND 4",
            name="ck_billing_currency__minor_unit",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class TaxCode(ModelBase, _GlobalDefinitionMixin):
    """A reusable global tax classification."""

    __tablename__ = "billing_tax_code"
    __table_args__ = ({"schema": CORE_SCHEMA_TOKEN},)


class TaxRate(ModelBase):
    """An effective-dated tax rate for a tax code and jurisdiction."""

    __tablename__ = "billing_tax_rate"

    code: Mapped[str] = mapped_column(CITEXT(128), nullable=False, unique=True)
    tax_code_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.billing_tax_code.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    jurisdiction_code: Mapped[str] = mapped_column(CITEXT(64), nullable=False)
    rate_basis_points: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(jurisdiction_code)) > 0",
            name="ck_billing_tax_rate__jurisdiction_nonempty",
        ),
        CheckConstraint(
            "rate_basis_points BETWEEN 0 AND 10000",
            name="ck_billing_tax_rate__basis_points",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_billing_tax_rate__effective_bounds",
        ),
        Index(
            "ix_billing_tax_rate__tax_jurisdiction_effective",
            "tax_code_id",
            "jurisdiction_code",
            "effective_from",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class PaymentTerm(ModelBase, _GlobalDefinitionMixin):
    """A reusable global payment-term definition."""

    __tablename__ = "billing_payment_term"

    due_days: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("due_days >= 0", name="ck_billing_payment_term__due_days"),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class InvoiceTemplate(ModelBase, _GlobalDefinitionMixin):
    """A reusable invoice document template definition."""

    __tablename__ = "billing_invoice_template"

    locale: Mapped[str] = mapped_column(CITEXT(32), nullable=False)
    template_format: Mapped[str] = mapped_column(CITEXT(16), nullable=False)
    subject_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "template_format IN ('html', 'text')",
            name="ck_billing_invoice_template__format",
        ),
        CheckConstraint(
            "length(btrim(body_template)) > 0",
            name="ck_billing_invoice_template__body_nonempty",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )


class DiscountDefinition(ModelBase, _GlobalDefinitionMixin):
    """A reusable discount definition with an optional coupon code."""

    __tablename__ = "billing_discount_definition"

    kind: Mapped[str] = mapped_column(CITEXT(32), nullable=False)
    percentage_basis_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency_definition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.billing_currency_definition.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )
    coupon_code: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        unique=True,
    )
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('percentage', 'fixed_amount')",
            name="ck_billing_discount_definition__kind",
        ),
        CheckConstraint(
            "percentage_basis_points IS NULL OR "
            "percentage_basis_points BETWEEN 0 AND 10000",
            name="ck_billing_discount_definition__percentage",
        ),
        CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_billing_discount_definition__amount",
        ),
        CheckConstraint(
            "(kind = 'percentage' AND percentage_basis_points IS NOT NULL "
            "AND amount IS NULL AND currency_definition_id IS NULL) OR "
            "(kind = 'fixed_amount' AND percentage_basis_points IS NULL "
            "AND amount IS NOT NULL AND currency_definition_id IS NOT NULL)",
            name="ck_billing_discount_definition__benefit_shape",
        ),
        CheckConstraint(
            "coupon_code IS NULL OR length(btrim(coupon_code)) > 0",
            name="ck_billing_discount_definition__coupon_nonempty",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_billing_discount_definition__valid_bounds",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )
