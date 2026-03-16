"""Provides an ORM for ops_vpn vendors."""

from __future__ import annotations

__all__ = ["Vendor", "VendorLifecycleStatus"]

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.soft_delete import SoftDeleteMixin
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin

if TYPE_CHECKING:
    from mugen.core.plugin.ops_vpn.model.vendor_performance_event import (
        VendorPerformanceEvent,
    )


class VendorLifecycleStatus(str, enum.Enum):
    """Vendor lifecycle states."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELISTED = "delisted"


# pylint: disable=too-few-public-methods
class Vendor(ModelBase, TenantScopedMixin, SoftDeleteMixin):
    """An ORM for ops_vpn vendors."""

    __tablename__ = "ops_vpn_vendor"

    code: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    display_name: Mapped[str] = mapped_column(
        CITEXT(256),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            VendorLifecycleStatus,
            name="ops_vpn_vendor_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'candidate'"),
    )

    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    reverification_cadence_days: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("365"),
    )

    last_reverified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    next_reverification_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
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

    categories: Mapped[list["VendorCategory"]] = relationship(  # type: ignore
        back_populates="vendor",
        cascade="save-update, merge",
    )

    capabilities: Mapped[list["VendorCapability"]] = relationship(  # type: ignore
        back_populates="vendor",
        cascade="save-update, merge",
    )

    verifications: Mapped[list["VendorVerification"]] = relationship(  # type: ignore
        back_populates="vendor",
        cascade="save-update, merge",
    )

    performance_events: Mapped[list["VendorPerformanceEvent"]] = relationship(
        back_populates="vendor",
        cascade="save-update, merge",
    )

    scorecards: Mapped[list["VendorScorecard"]] = relationship(  # type: ignore
        back_populates="vendor",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_vendor__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_ops_vpn_vendor__display_name_nonempty",
        ),
        CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_ops_vpn_vendor__external_ref_nonempty_if_set",
        ),
        CheckConstraint(
            "reverification_cadence_days > 0",
            name="ck_ops_vpn_vendor__reverification_cadence_days_positive",
        ),
        CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_vpn_vendor__not_deleted_and_not_deleted_by",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_vendor__tenant_code",
        ),
        Index(
            "ix_ops_vpn_vendor__tenant_status",
            "tenant_id",
            "status",
        ),
        Index(
            "ix_ops_vpn_vendor__tenant_reverification_due",
            "tenant_id",
            "next_reverification_due_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"Vendor(id={self.id!r})"
