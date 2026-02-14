"""Provides an ORM for vendor scorecard snapshots."""

from __future__ import annotations

__all__ = ["VendorScorecard"]

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class VendorScorecard(ModelBase, TenantScopedMixin):
    """An ORM for vendor scorecard snapshots."""

    __tablename__ = "ops_vpn_vendor_scorecard"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    time_to_quote_score: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    completion_rate_score: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    complaint_rate_score: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    response_sla_score: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    overall_score: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    event_count: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    is_routable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
        index=True,
    )

    status_flags: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    vendor: Mapped["Vendor"] = relationship(  # type: ignore
        back_populates="scorecards",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            ("mugen.ops_vpn_vendor.tenant_id", "mugen.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_scorecard__tenant_vendor",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "period_end >= period_start",
            name="ck_ops_vpn_vendor_scorecard__period_end_gte_start",
        ),
        CheckConstraint(
            "event_count >= 0",
            name="ck_ops_vpn_vendor_scorecard__event_count_nonneg",
        ),
        CheckConstraint(
            "time_to_quote_score IS NULL OR "
            "(time_to_quote_score >= 0 AND time_to_quote_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__time_to_quote_score_range",
        ),
        CheckConstraint(
            "completion_rate_score IS NULL OR "
            "(completion_rate_score >= 0 AND completion_rate_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__completion_rate_score_range",
        ),
        CheckConstraint(
            "complaint_rate_score IS NULL OR "
            "(complaint_rate_score >= 0 AND complaint_rate_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__complaint_rate_score_range",
        ),
        CheckConstraint(
            "response_sla_score IS NULL OR (response_sla_score >= 0 AND"
            " response_sla_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__response_sla_score_range",
        ),
        CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__overall_score_range",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_scorecard__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "period_start",
            "period_end",
            name="ux_ops_vpn_vendor_scorecard__tenant_vendor_period",
        ),
        Index(
            "ix_ops_vpn_vendor_scorecard__tenant_vendor_period_end",
            "tenant_id",
            "vendor_id",
            "period_end",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"VendorScorecard(id={self.id!r})"
