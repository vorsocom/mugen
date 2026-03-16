"""Provides an ORM for billing usage allocations."""

__all__ = ["UsageAllocation"]

import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class UsageAllocation(ModelBase, TenantScopedMixin):
    """An ORM for allocation of usage events into entitlement buckets."""

    __tablename__ = "billing_usage_allocation"

    usage_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    entitlement_bucket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    allocated_quantity: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
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

    usage_event: Mapped["UsageEvent"] = relationship(  # type: ignore
        back_populates="usage_allocations",
    )

    entitlement_bucket: Mapped["EntitlementBucket"] = relationship(  # type: ignore
        back_populates="usage_allocations",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "usage_event_id"),
            ("mugen.billing_usage_event.tenant_id", "mugen.billing_usage_event.id"),
            name="fkx_billing_usage_allocation__tenant_usage_event",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "entitlement_bucket_id"),
            (
                "mugen.billing_entitlement_bucket.tenant_id",
                "mugen.billing_entitlement_bucket.id",
            ),
            name="fkx_billing_usage_allocation__tenant_entitlement_bucket",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "allocated_quantity > 0",
            name="ck_billing_usage_allocation__allocated_positive",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_usage_allocation__external_ref_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_usage_allocation__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "usage_event_id",
            "entitlement_bucket_id",
            name="ux_billing_usage_allocation__tenant_usage_event_bucket",
        ),
        Index(
            "ix_billing_usage_allocation__tenant_usage_event",
            "tenant_id",
            "usage_event_id",
        ),
        Index(
            "ix_billing_usage_allocation__tenant_entitlement_bucket",
            "tenant_id",
            "entitlement_bucket_id",
        ),
        Index(
            "ux_billing_usage_allocation__tenant_external_ref",
            "tenant_id",
            "external_ref",
            unique=True,
            postgresql_where=sa_text("external_ref IS NOT NULL"),
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"UsageAllocation(id={self.id!r})"
