"""SQLAlchemy models for the agent_runtime plugin."""

from __future__ import annotations

__all__ = [
    "AgentPlanRun",
    "AgentPlanStep",
    "metadata",
]

from datetime import datetime
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase
from mugen.core.plugin.acp.model.mixin.tenant_scoped import TenantScopedMixin
from mugen.core.utility.rdbms_schema import AGENT_RUNTIME_SCHEMA_TOKEN

_SCHEMA = AGENT_RUNTIME_SCHEMA_TOKEN


class AgentPlanRun(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """Durable plan-run row."""

    __tablename__ = "agent_runtime_plan_run"

    scope_key: Mapped[str] = mapped_column(CITEXT(255), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)
    service_route_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{_SCHEMA}.agent_runtime_plan_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    root_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{_SCHEMA}.agent_runtime_plan_run.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_key: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    spawned_by_step_no: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    request_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    policy_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    run_state_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    join_state_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    current_sequence_no: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=sa_text("0"),
    )
    next_wakeup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    lease_owner: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    final_outcome_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_agent_run__scope_key",
        ),
        CheckConstraint("length(btrim(mode)) > 0", name="ck_agent_run__mode"),
        CheckConstraint("length(btrim(status)) > 0", name="ck_agent_run__status"),
        CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_agent_run__service_route_nonempty_if_set",
        ),
        CheckConstraint(
            "agent_key IS NULL OR length(btrim(agent_key)) > 0",
            name="ck_agent_run__agent_key_nonempty_if_set",
        ),
        {
            "schema": _SCHEMA,
        },
    )


class AgentPlanStep(
    ModelBase, TenantScopedMixin
):  # pylint: disable=too-few-public-methods
    """Append-only run-step row."""

    __tablename__ = "agent_runtime_plan_step"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{_SCHEMA}.agent_runtime_plan_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence_no: Mapped[int] = mapped_column(BigInteger, nullable=False)
    step_kind: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "sequence_no",
            name="ux_agent_step__tenant_run_sequence",
        ),
        CheckConstraint(
            "length(btrim(step_kind)) > 0",
            name="ck_agent_step__step_kind",
        ),
        {
            "schema": _SCHEMA,
        },
    )


Index(
    "ix_agent_run__tenant_mode_status",
    AgentPlanRun.tenant_id,
    AgentPlanRun.mode,
    AgentPlanRun.status,
)
Index(
    "ix_agent_run__tenant_parent",
    AgentPlanRun.tenant_id,
    AgentPlanRun.parent_run_id,
)
Index(
    "ix_agent_run__tenant_root",
    AgentPlanRun.tenant_id,
    AgentPlanRun.root_run_id,
)
Index(
    "ix_agent_run__tenant_agent",
    AgentPlanRun.tenant_id,
    AgentPlanRun.agent_key,
)
Index(
    "ix_agent_step__tenant_run_occurred",
    AgentPlanStep.tenant_id,
    AgentPlanStep.run_id,
    AgentPlanStep.occurred_at,
)

metadata = MetaData()
for table in (
    AgentPlanRun.__table__,
    AgentPlanStep.__table__,
):
    table.to_metadata(metadata)
