"""Provides an ORM for billing products."""

__all__ = ["Product"]

from typing import List

from sqlalchemy import (
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class Product(ModelBase, SoftDeleteMixin):
    """An ORM for billing products."""

    __tablename__ = "billing_product"

    code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(256),
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    prices: Mapped[List["Price"]] = relationship(  # type: ignore
        back_populates="product",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_billing_product__code_nonempty",
        ),
        CheckConstraint(
            "code = btrim(code)",
            name="ck_billing_product__code_trimmed",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_billing_product__name_nonempty",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_product__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "code",
            name="ux_billing_product__code",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"Product(id={self.id!r})"
