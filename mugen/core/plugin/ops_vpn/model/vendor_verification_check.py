"""Provides an ORM for vendor verification checklist checks."""

from __future__ import annotations

__all__ = ["VendorVerificationCheck"]

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class VendorVerificationCheck(ModelBase, TenantScopedMixin):
    """An ORM for criterion checks completed during a verification."""

    __tablename__ = "ops_vpn_vendor_verification_check"

    vendor_verification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    criterion_code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        CITEXT(32),
        nullable=False,
        server_default=sa_text("'pending'"),
        index=True,
    )

    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )

    checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    vendor_verification: Mapped["VendorVerification"] = relationship(  # type: ignore
        back_populates="checks",
    )

    criterion: Mapped["VerificationCriterion | None"] = relationship(  # type: ignore
        back_populates="checks",
    )

    artifacts: Mapped[list["VendorVerificationArtifact"]] = relationship(
        # type: ignore
        back_populates="verification_check",
        cascade="save-update, merge",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_verification_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_vpn_vendor_verification.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_vpn_vendor_verification.id",
            ),
            name="fkx_ops_vpn_vendor_verification_check__tenant_verification",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "criterion_id"),
            (
                f"{CORE_SCHEMA_TOKEN}.ops_vpn_verification_criterion.tenant_id",
                f"{CORE_SCHEMA_TOKEN}.ops_vpn_verification_criterion.id",
            ),
            name="fkx_ops_vpn_vendor_verification_check__tenant_criterion",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(criterion_code)) > 0",
            name="ck_ops_vpn_vendor_verification_check__criterion_code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_ops_vpn_vendor_verification_check__status_nonempty",
        ),
        CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name="ck_ops_vpn_vendor_verification_check__notes_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_verification_check__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "vendor_verification_id",
            "criterion_code",
            name="ux_ops_vpn_vendor_verif_check__tenant_verif_criterion",
        ),
        Index(
            "ix_ops_vpn_vendor_verif_check__tenant_verif_status",
            "tenant_id",
            "vendor_verification_id",
            "status",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"VendorVerificationCheck(id={self.id!r})"
