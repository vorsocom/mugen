"""Provides an ORM for vendor categories."""

from __future__ import annotations

__all__ = ["VendorCategory"]

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class VendorCategory(ModelBase, TenantScopedMixin):
    """An ORM for vendor category assignments."""

    __tablename__ = "ops_vpn_vendor_category"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    category_code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        CITEXT(256),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    vendor: Mapped["Vendor"] = relationship(  # type: ignore
        back_populates="categories",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            ("mugen.ops_vpn_vendor.tenant_id", "mugen.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_category__tenant_vendor",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(category_code)) > 0",
            name="ck_ops_vpn_vendor_category__category_code_nonempty",
        ),
        CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_ops_vpn_vendor_category__display_name_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_category__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "category_code",
            name="ux_ops_vpn_vendor_category__tenant_vendor_category_code",
        ),
        Index(
            "ix_ops_vpn_vendor_category__tenant_category",
            "tenant_id",
            "category_code",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"VendorCategory(id={self.id!r})"
