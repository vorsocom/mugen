"""Provides an ORM for ops_vpn taxonomy subcategories."""

from __future__ import annotations

__all__ = ["TaxonomySubcategory"]

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class TaxonomySubcategory(ModelBase, TenantScopedMixin):
    """An ORM for taxonomy subcategories (DDCCSS level)."""

    __tablename__ = "ops_vpn_taxonomy_subcategory"

    taxonomy_category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        CITEXT(16),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(256),
        nullable=False,
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    category: Mapped["TaxonomyCategory"] = relationship(  # type: ignore
        back_populates="subcategories",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "taxonomy_category_id"),
            (
                "mugen.ops_vpn_taxonomy_category.tenant_id",
                "mugen.ops_vpn_taxonomy_category.id",
            ),
            name="fkx_ops_vpn_taxonomy_subcategory__tenant_category",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_taxonomy_subcategory__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_taxonomy_subcategory__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_taxonomy_subcategory__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_taxonomy_subcategory__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_taxonomy_subcategory__tenant_code",
        ),
        Index(
            "ix_ops_vpn_taxonomy_subcategory__tenant_category_code",
            "tenant_id",
            "taxonomy_category_id",
            "code",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"TaxonomySubcategory(id={self.id!r})"
