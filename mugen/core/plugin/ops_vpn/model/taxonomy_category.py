"""Provides an ORM for ops_vpn taxonomy categories."""

from __future__ import annotations

__all__ = ["TaxonomyCategory"]

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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class TaxonomyCategory(ModelBase, TenantScopedMixin):
    """An ORM for taxonomy categories (DDCC level)."""

    __tablename__ = "ops_vpn_taxonomy_category"

    taxonomy_domain_id: Mapped[uuid.UUID] = mapped_column(
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

    domain: Mapped["TaxonomyDomain"] = relationship(  # type: ignore
        back_populates="categories",
    )

    subcategories: Mapped[list["TaxonomySubcategory"]] = relationship(  # type: ignore
        back_populates="category",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "taxonomy_domain_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_vpn_taxonomy_domain.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_vpn_taxonomy_domain.id",
            ),
            name="fkx_ops_vpn_taxonomy_category__tenant_domain",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_taxonomy_category__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_taxonomy_category__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_taxonomy_category__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_taxonomy_category__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_taxonomy_category__tenant_code",
        ),
        Index(
            "ix_ops_vpn_taxonomy_category__tenant_domain_code",
            "tenant_id",
            "taxonomy_domain_id",
            "code",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"TaxonomyCategory(id={self.id!r})"
