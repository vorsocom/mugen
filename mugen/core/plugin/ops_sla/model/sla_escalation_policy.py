"""Provides an ORM for SLA escalation trigger/action policy definitions."""

from __future__ import annotations

__all__ = ["SlaEscalationPolicy"]

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
from mugen.core.utility.rdbms_schema import CORE_SCHEMA_TOKEN


class SlaEscalationPolicy(ModelBase, TenantScopedMixin):
    """An ORM for deterministic escalation policy matching and plan generation."""

    __tablename__ = "ops_sla_escalation_policy"

    policy_key: Mapped[str] = mapped_column(
        CITEXT(128),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        CITEXT(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        CITEXT(1024),
        nullable=True,
    )

    priority: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("100"),
    )

    triggers_json: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    actions_json: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_text("true"),
        index=True,
    )

    attributes: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "length(btrim(policy_key)) > 0",
            name="ck_ops_sla_escalation_policy__policy_key_nonempty",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_escalation_policy__name_nonempty",
        ),
        CheckConstraint(
            "priority >= 0",
            name="ck_ops_sla_escalation_policy__priority_nonnegative",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_escalation_policy__tenant_id_id",
        ),
        UniqueConstraint(
            "tenant_id",
            "policy_key",
            name="ux_ops_sla_escalation_policy__tenant_policy_key",
        ),
        Index(
            "ix_ops_sla_escalation_policy__tenant_active_priority",
            "tenant_id",
            "is_active",
            "priority",
        ),
        {"schema": CORE_SCHEMA_TOKEN},
    )

    def __repr__(self) -> str:
        return f"SlaEscalationPolicy(id={self.id!r})"
