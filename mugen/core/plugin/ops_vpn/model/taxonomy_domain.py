"""Provides an ORM for ops_vpn taxonomy domains."""

from __future__ import annotations

__all__ = ["TaxonomyDomain"]

from sqlalchemy import (
    CheckConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class TaxonomyDomain(ModelBase, TenantScopedMixin):
    """An ORM for taxonomy domains (DD level)."""

    __tablename__ = "ops_vpn_taxonomy_domain"

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

    categories: Mapped[list["TaxonomyCategory"]] = relationship(  # type: ignore
        back_populates="domain",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_taxonomy_domain__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_taxonomy_domain__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_taxonomy_domain__description_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_taxonomy_domain__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_taxonomy_domain__tenant_code",
        ),
        Index(
            "ix_ops_vpn_taxonomy_domain__tenant_code",
            "tenant_id",
            "code",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"TaxonomyDomain(id={self.id!r})"
