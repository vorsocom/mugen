"""init agent runtime

Revision ID: 1f2e3d4c5b6a
Revises:
Create Date: 2026-03-10 13:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_core_schema, resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1f2e3d4c5b6a"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CORE_SCHEMA = resolve_core_schema(default=resolve_runtime_schema())


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    ]


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey(f"{_CORE_SCHEMA}.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_runtime_plan_run",
        *_base_columns(),
        _tenant_column(),
        sa.Column("scope_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("mode", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("status", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("service_route_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "current_sequence_no",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("next_wakeup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "final_outcome_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_agent_run__scope_key",
        ),
        sa.CheckConstraint(
            "length(btrim(mode)) > 0",
            name="ck_agent_run__mode",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_agent_run__status",
        ),
        sa.CheckConstraint(
            (
                "service_route_key IS NULL OR "
                "length(btrim(service_route_key)) > 0"
            ),
            name="ck_agent_run__service_route_nonempty_if_set",
        ),
    )
    for index_name, columns in (
        ("ix_agent_runtime_plan_run_tenant_id", ["tenant_id"]),
        ("ix_agent_runtime_plan_run_scope_key", ["scope_key"]),
        ("ix_agent_runtime_plan_run_mode", ["mode"]),
        ("ix_agent_runtime_plan_run_status", ["status"]),
        ("ix_agent_runtime_plan_run_service_route_key", ["service_route_key"]),
        ("ix_agent_runtime_plan_run_next_wakeup_at", ["next_wakeup_at"]),
        ("ix_agent_runtime_plan_run_lease_expires_at", ["lease_expires_at"]),
    ):
        op.create_index(index_name, "agent_runtime_plan_run", columns)
    op.create_index(
        "ix_agent_run__tenant_mode_status",
        "agent_runtime_plan_run",
        ["tenant_id", "mode", "status"],
    )

    op.create_table(
        "agent_runtime_plan_step",
        *_base_columns(),
        _tenant_column(),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runtime_plan_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.BigInteger(), nullable=False),
        sa.Column("step_kind", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "sequence_no",
            name="ux_agent_step__tenant_run_sequence",
        ),
        sa.CheckConstraint(
            "length(btrim(step_kind)) > 0",
            name="ck_agent_step__step_kind",
        ),
    )
    for index_name, columns in (
        ("ix_agent_runtime_plan_step_tenant_id", ["tenant_id"]),
        ("ix_agent_runtime_plan_step_run_id", ["run_id"]),
        ("ix_agent_runtime_plan_step_step_kind", ["step_kind"]),
        ("ix_agent_runtime_plan_step_occurred_at", ["occurred_at"]),
    ):
        op.create_index(index_name, "agent_runtime_plan_step", columns)
    op.create_index(
        "ix_agent_step__tenant_run_occurred",
        "agent_runtime_plan_step",
        ["tenant_id", "run_id", "occurred_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    for index_name in (
        "ix_agent_step__tenant_run_occurred",
        "ix_agent_runtime_plan_step_occurred_at",
        "ix_agent_runtime_plan_step_step_kind",
        "ix_agent_runtime_plan_step_run_id",
        "ix_agent_runtime_plan_step_tenant_id",
    ):
        op.drop_index(index_name, table_name="agent_runtime_plan_step")
    op.drop_table("agent_runtime_plan_step")

    for index_name in (
        "ix_agent_run__tenant_mode_status",
        "ix_agent_runtime_plan_run_lease_expires_at",
        "ix_agent_runtime_plan_run_next_wakeup_at",
        "ix_agent_runtime_plan_run_service_route_key",
        "ix_agent_runtime_plan_run_status",
        "ix_agent_runtime_plan_run_mode",
        "ix_agent_runtime_plan_run_scope_key",
        "ix_agent_runtime_plan_run_tenant_id",
    ):
        op.drop_index(index_name, table_name="agent_runtime_plan_run")
    op.drop_table("agent_runtime_plan_run")
