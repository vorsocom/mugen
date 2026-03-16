"""Provides an ORM for vendor verification evidence artifacts."""

from __future__ import annotations

__all__ = ["VendorVerificationArtifact"]

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
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class VendorVerificationArtifact(ModelBase, TenantScopedMixin):
    """An ORM for evidence artifacts linked to verifications/checks."""

    __tablename__ = "ops_vpn_vendor_verification_artifact"

    vendor_verification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    verification_check_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    artifact_type: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        index=True,
    )

    uri: Mapped[str | None] = mapped_column(
        CITEXT(1024),
        nullable=True,
    )

    content_hash: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
    )

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("mugen.admin_user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
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
        back_populates="artifacts",
    )

    verification_check: Mapped["VendorVerificationCheck | None"] = relationship(
        # type: ignore
        back_populates="artifacts",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_verification_id"),
            (
                "mugen.ops_vpn_vendor_verification.tenant_id",
                "mugen.ops_vpn_vendor_verification.id",
            ),
            name="fkx_ops_vpn_vendor_verification_artifact__tenant_verification",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "verification_check_id"),
            (
                "mugen.ops_vpn_vendor_verification_check.tenant_id",
                "mugen.ops_vpn_vendor_verification_check.id",
            ),
            name="fkx_ops_vpn_vendor_verification_artifact__tenant_check",
            ondelete="SET NULL",
        ),
        CheckConstraint(
            "length(btrim(artifact_type)) > 0",
            name="ck_ops_vpn_vendor_verification_artifact__artifact_type_nonempty",
        ),
        CheckConstraint(
            "uri IS NULL OR length(btrim(uri)) > 0",
            name="ck_ops_vpn_vendor_verification_artifact__uri_nonempty_if_set",
        ),
        CheckConstraint(
            "content_hash IS NULL OR length(btrim(content_hash)) > 0",
            name="ck_ops_vpn_vendor_verif_artifact__content_hash_nonempty",
        ),
        CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name="ck_ops_vpn_vendor_verification_artifact__notes_nonempty_if_set",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_verification_artifact__tenant_id_id",
        ),
        Index(
            "ix_ops_vpn_vendor_verif_artifact__tenant_verif_uploaded",
            "tenant_id",
            "vendor_verification_id",
            "uploaded_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"VendorVerificationArtifact(id={self.id!r})"
