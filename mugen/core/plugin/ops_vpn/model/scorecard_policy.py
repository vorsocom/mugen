"""Provides an ORM for ops_vpn scorecard policy configuration."""

from __future__ import annotations

__all__ = ["ScorecardPolicy"]

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin


# pylint: disable=too-few-public-methods
class ScorecardPolicy(ModelBase, TenantScopedMixin):
    """Tenant-scoped scorecard rollup policy."""

    __tablename__ = "ops_vpn_scorecard_policy"

    code: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'default'"),
        index=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
    )

    time_to_quote_weight: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("25"),
    )

    completion_rate_weight: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("25"),
    )

    complaint_rate_weight: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("25"),
    )

    response_sla_weight: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("25"),
    )

    min_sample_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("1"),
    )

    minimum_overall_score: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )

    require_all_metrics: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("false"),
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_scorecard_policy__code_nonempty",
        ),
        CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_ops_vpn_scorecard_policy__display_name_nonempty_if_set",
        ),
        CheckConstraint(
            "time_to_quote_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__time_to_quote_weight_nonneg",
        ),
        CheckConstraint(
            "completion_rate_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__completion_rate_weight_nonneg",
        ),
        CheckConstraint(
            "complaint_rate_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__complaint_rate_weight_nonneg",
        ),
        CheckConstraint(
            "response_sla_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__response_sla_weight_nonneg",
        ),
        CheckConstraint(
            "(time_to_quote_weight + completion_rate_weight + complaint_rate_weight +"
            " response_sla_weight) > 0",
            name="ck_ops_vpn_scorecard_policy__weight_sum_positive",
        ),
        CheckConstraint(
            "min_sample_size > 0",
            name="ck_ops_vpn_scorecard_policy__min_sample_size_positive",
        ),
        CheckConstraint(
            "minimum_overall_score >= 0 AND minimum_overall_score <= 100",
            name="ck_ops_vpn_scorecard_policy__minimum_overall_score_range",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_scorecard_policy__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_scorecard_policy__tenant_code",
        ),
        Index(
            "ix_ops_vpn_scorecard_policy__tenant_code",
            "tenant_id",
            "code",
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"ScorecardPolicy(id={self.id!r})"
