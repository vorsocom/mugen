"""Provides an ORM for billing prices."""

__all__ = ["Price", "PriceType", "IntervalUnit"]

import enum
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class PriceType(str, enum.Enum):
    """Price type enum."""

    ONE_TIME = "one_time"
    RECURRING = "recurring"
    METERED = "metered"


class IntervalUnit(str, enum.Enum):
    """Billing interval unit enum."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


# pylint: disable=too-few-public-methods
class Price(ModelBase, SoftDeleteMixin):
    """An ORM for billing prices."""

    __tablename__ = "billing_price"

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            f"{CORE_SCHEMA_TOKEN}.billing_product.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    price_type: Mapped[str] = mapped_column(
        PGENUM(
            PriceType,
            name="billing_price_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'one_time'"),
    )

    currency: Mapped[str] = mapped_column(
        CITEXT(3),
        nullable=False,
        index=True,
    )

    unit_amount: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    interval_unit: Mapped[str | None] = mapped_column(
        PGENUM(
            IntervalUnit,
            name="billing_interval_unit",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=True,
        index=True,
    )

    interval_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    trial_period_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    usage_unit: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
    )

    meter_code: Mapped[str | None] = mapped_column(
        CITEXT(64),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    product: Mapped["Product"] = relationship(  # type: ignore
        back_populates="prices",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_billing_price__code_nonempty",
        ),
        CheckConstraint(
            "code = btrim(code)",
            name="ck_billing_price__code_trimmed",
        ),
        CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_price__currency_len3",
        ),
        CheckConstraint(
            "unit_amount IS NULL OR unit_amount >= 0",
            name="ck_billing_price__unit_amount_nonneg_if_set",
        ),
        CheckConstraint(
            "interval_count IS NULL OR interval_count > 0",
            name="ck_billing_price__interval_count_positive_if_set",
        ),
        CheckConstraint(
            "trial_period_days IS NULL OR trial_period_days >= 0",
            name="ck_billing_price__trial_period_nonneg_if_set",
        ),
        CheckConstraint(
            "usage_unit IS NULL OR length(btrim(usage_unit)) > 0",
            name="ck_billing_price__usage_unit_nonempty_if_set",
        ),
        CheckConstraint(
            "meter_code IS NULL OR length(btrim(meter_code)) > 0",
            name="ck_billing_price__meter_code_nonempty_if_set",
        ),
        CheckConstraint(
            "(meter_code IS NULL) = (usage_unit IS NULL)",
            name="ck_billing_price__meter_pair_complete",
        ),
        CheckConstraint(
            (
                "price_type <> 'metered' OR "
                "(meter_code IS NOT NULL AND usage_unit IS NOT NULL)"
            ),
            name="ck_billing_price__metered_pair_required",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_price__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "product_id",
            "code",
            name="ux_billing_price__product_code",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"Price(id={self.id!r})"
