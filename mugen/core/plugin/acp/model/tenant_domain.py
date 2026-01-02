"""Provides an ORM for tenant domains."""

__all__ = ["TenantDomain"]

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class TenantDomain(ModelBase, TenantScopedMixin):
    """An ORM for tenant domains."""

    __tablename__ = "admin_tenant_domain"

    domain: Mapped[str] = mapped_column(
        CITEXT(253),
        unique=True,
        nullable=False,
    )

    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_false(),
    )

    tenant: Mapped["Tenant"] = relationship(  # type: ignore
        back_populates="tenant_domains",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(domain)) > 0",
            name="ck_tenant_domain__domain_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_tenant_domain__tenant_id_id",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"TenantDomain(id={self.id!r})"
