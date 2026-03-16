"""Provides an ORM for vendor onboarding and reverification checks."""

from __future__ import annotations

__all__ = ["VendorVerification", "VendorVerificationType", "VendorVerificationStatus"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class VendorVerificationType(str, enum.Enum):
    """Verification categories."""

    ONBOARDING = "onboarding"
    REVERIFICATION = "reverification"


class VendorVerificationStatus(str, enum.Enum):
    """Verification result states."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


# pylint: disable=too-few-public-methods
class VendorVerification(ModelBase, TenantScopedMixin):
    """An ORM for vendor onboarding/reverification checks."""

    __tablename__ = "ops_vpn_vendor_verification"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    verification_type: Mapped[str] = mapped_column(
        PGENUM(
            VendorVerificationType,
            name="ops_vpn_vendor_verification_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        PGENUM(
            VendorVerificationStatus,
            name="ops_vpn_vendor_verification_status",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
        server_default=sa_text("'pending'"),
    )

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    checked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey(f"{CORE_SCHEMA_TOKEN}.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    vendor: Mapped["Vendor"] = relationship(  # type: ignore
        back_populates="verifications",
    )

    checks: Mapped[list["VendorVerificationCheck"]] = relationship(  # type: ignore
        back_populates="vendor_verification",
        cascade="save-update, merge",
    )

    artifacts: Mapped[list["VendorVerificationArtifact"]] = relationship(
        # type: ignore
        back_populates="vendor_verification",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{CORE_SCHEMA_TOKEN}.ops_vpn_vendor.tenant_id", f"{CORE_SCHEMA_TOKEN}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_verification__tenant_vendor",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name="ck_ops_vpn_vendor_verification__notes_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_verification__tenant_id_id",
        ),
        Index(
            "ix_ops_vpn_vendor_verification__tenant_vendor_checked",
            "tenant_id",
            "vendor_id",
            "checked_at",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"VendorVerification(id={self.id!r})"
