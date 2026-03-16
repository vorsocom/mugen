"""Provides an ORM for vendor performance events."""

from __future__ import annotations

__all__ = ["VendorPerformanceEvent", "VendorMetricType"]

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM as PGENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


class VendorMetricType(str, enum.Enum):
    """Supported operational metric types."""

    TIME_TO_QUOTE = "time_to_quote"
    COMPLETION_RATE = "completion_rate"
    COMPLAINT_RATE = "complaint_rate"
    RESPONSE_SLA_ADHERENCE = "response_sla_adherence"


# pylint: disable=too-few-public-methods
class VendorPerformanceEvent(ModelBase, TenantScopedMixin):
    """An ORM for vendor performance observations."""

    __tablename__ = "ops_vpn_vendor_performance_event"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        nullable=False,
        index=True,
    )

    metric_type: Mapped[str] = mapped_column(
        PGENUM(
            VendorMetricType,
            name="ops_vpn_vendor_metric_type",
            values_callable=lambda items: [item.value for item in items],
            create_type=True,
        ),
        nullable=False,
        index=True,
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    metric_value: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    metric_numerator: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    metric_denominator: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    normalized_score: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    sample_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    unit: Mapped[str | None] = mapped_column(
        CITEXT(32),
        nullable=True,
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    vendor: Mapped["Vendor"] = relationship(  # type: ignore
        back_populates="performance_events",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            ("mugen.ops_vpn_vendor.tenant_id", "mugen.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_performance_event__tenant_vendor",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "metric_value IS NULL OR metric_value >= 0",
            name="ck_ops_vpn_vendor_performance_event__metric_value_nonneg",
        ),
        CheckConstraint(
            "metric_numerator IS NULL OR metric_numerator >= 0",
            name="ck_ops_vpn_vendor_performance_event__metric_numerator_nonneg",
        ),
        CheckConstraint(
            "metric_denominator IS NULL OR metric_denominator > 0",
            name="ck_ops_vpn_vendor_performance_event__metric_denominator_positive",
        ),
        CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <="
            " 100)",
            name="ck_ops_vpn_vendor_performance_event__normalized_score_range",
        ),
        CheckConstraint(
            "sample_size > 0",
            name="ck_ops_vpn_vendor_performance_event__sample_size_positive",
        ),
        CheckConstraint(
            "metric_value IS NOT NULL OR normalized_score IS NOT NULL OR "
            "(metric_numerator IS NOT NULL AND metric_denominator IS NOT NULL)",
            name="ck_ops_vpn_vendor_performance_event__value_or_score_present",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_performance_event__tenant_id_id",
        ),
        Index(
            "ix_ops_vpn_vendor_performance_event__tenant_vendor_metric_observed",
            "tenant_id",
            "vendor_id",
            "metric_type",
            "observed_at",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"VendorPerformanceEvent(id={self.id!r})"
