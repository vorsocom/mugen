"""Provides an ORM for vendor capabilities."""

from __future__ import annotations

__all__ = ["VendorCapability"]

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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class VendorCapability(ModelBase, TenantScopedMixin):
    """An ORM for vendor capabilities and service regions."""

    __tablename__ = "ops_vpn_vendor_capability"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    capability_code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    service_region: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    vendor: Mapped["Vendor"] = relationship(  # type: ignore
        back_populates="capabilities",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{CORE_SCHEMA_TOKEN}.ops_vpn_vendor.tenant_id", f"{CORE_SCHEMA_TOKEN}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_capability__tenant_vendor",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "length(btrim(capability_code)) > 0",
            name="ck_ops_vpn_vendor_capability__capability_code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(service_region)) > 0",
            name="ck_ops_vpn_vendor_capability__service_region_nonempty",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_capability__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "capability_code",
            "service_region",
            name="ux_ops_vpn_vendor_capability__tenant_vendor_capability_region",
        ),
        Index(
            "ix_ops_vpn_vendor_capability__tenant_capability_region",
            "tenant_id",
            "capability_code",
            "service_region",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"VendorCapability(id={self.id!r})"
