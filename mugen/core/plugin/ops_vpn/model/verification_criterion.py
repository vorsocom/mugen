"""Provides an ORM for generic verification checklist criteria."""

from __future__ import annotations

__all__ = ["VerificationCriterion"]

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


# pylint: disable=too-few-public-methods
class VerificationCriterion(ModelBase, TenantScopedMixin):
    """An ORM for generic onboarding/reverification criteria."""

    __tablename__ = "ops_vpn_verification_criterion"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
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

    verification_type: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )

    is_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
    )

    sort_order: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    checks: Mapped[list["VendorVerificationCheck"]] = relationship(  # type: ignore
        back_populates="criterion",
        cascade="save-update, merge",
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_verification_criterion__code_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_verification_criterion__name_nonempty",
        ),
        CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_verification_criterion__description_nonempty_if_set",
        ),
        CheckConstraint(
            "verification_type IS NULL OR length(btrim(verification_type)) > 0",
            name="ck_ops_vpn_verif_criterion__verification_type_nonempty",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_ops_vpn_verification_criterion__sort_order_nonneg",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_verification_criterion__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_verification_criterion__tenant_code",
        ),
        Index(
            "ix_ops_vpn_verification_criterion__tenant_verification_type",
            "tenant_id",
            "verification_type",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"VerificationCriterion(id={self.id!r})"
