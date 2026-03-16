"""add multi agent lineage

Revision ID: 2a4c6e8f0a1b
Revises: 1f2e3d4c5b6a
Create Date: 2026-03-15 11:15:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2a4c6e8f0a1b"
down_revision: Union[str, Sequence[str], None] = "1f2e3d4c5b6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runtime_plan_run",
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "agent_runtime_plan_run",
        sa.Column("root_run_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "agent_runtime_plan_run",
        sa.Column("agent_key", postgresql.CITEXT(length=128), nullable=True),
    )
    op.add_column(
        "agent_runtime_plan_run",
        sa.Column("spawned_by_step_no", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "agent_runtime_plan_run",
        sa.Column(
            "join_state_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_agent_run__parent_run_id",
        "agent_runtime_plan_run",
        "agent_runtime_plan_run",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_run__root_run_id",
        "agent_runtime_plan_run",
        "agent_runtime_plan_run",
        ["root_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_agent_run__agent_key_nonempty_if_set",
        "agent_runtime_plan_run",
        "agent_key IS NULL OR length(btrim(agent_key)) > 0",
    )

    for index_name, columns in (
        ("ix_agent_runtime_plan_run_parent_run_id", ["parent_run_id"]),
        ("ix_agent_runtime_plan_run_root_run_id", ["root_run_id"]),
        ("ix_agent_runtime_plan_run_agent_key", ["agent_key"]),
        ("ix_agent_run__tenant_parent", ["tenant_id", "parent_run_id"]),
        ("ix_agent_run__tenant_root", ["tenant_id", "root_run_id"]),
        ("ix_agent_run__tenant_agent", ["tenant_id", "agent_key"]),
    ):
        op.create_index(index_name, "agent_runtime_plan_run", columns)


def downgrade() -> None:
    """Downgrade schema."""
    for index_name in (
        "ix_agent_run__tenant_agent",
        "ix_agent_run__tenant_root",
        "ix_agent_run__tenant_parent",
        "ix_agent_runtime_plan_run_agent_key",
        "ix_agent_runtime_plan_run_root_run_id",
        "ix_agent_runtime_plan_run_parent_run_id",
    ):
        op.drop_index(index_name, table_name="agent_runtime_plan_run")

    op.drop_constraint(
        "ck_agent_run__agent_key_nonempty_if_set",
        "agent_runtime_plan_run",
        type_="check",
    )
    op.drop_constraint(
        "fk_agent_run__root_run_id",
        "agent_runtime_plan_run",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_agent_run__parent_run_id",
        "agent_runtime_plan_run",
        type_="foreignkey",
    )

    op.drop_column("agent_runtime_plan_run", "join_state_json")
    op.drop_column("agent_runtime_plan_run", "spawned_by_step_no")
    op.drop_column("agent_runtime_plan_run", "agent_key")
    op.drop_column("agent_runtime_plan_run", "root_run_id")
    op.drop_column("agent_runtime_plan_run", "parent_run_id")
