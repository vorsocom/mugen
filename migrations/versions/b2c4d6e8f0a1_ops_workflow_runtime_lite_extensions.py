"""ops workflow runtime-lite replay/compensation extensions

Revision ID: b2c4d6e8f0a1
Revises: a2b4c6d8e0f1
Create Date: 2026-02-25 15:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import rewrite_mugen_schema_sql
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def _execute(statement) -> None:
    if isinstance(statement, str):
        op.execute(_sql(statement))
        return
    op.execute(statement)


# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "b2c4d6e8f0a1"
down_revision: Union[str, None] = "a2b4c6d8e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    _execute(
        "ALTER TYPE mugen.ops_workflow_event_type ADD VALUE IF NOT EXISTS 'replayed';"
    )
    _execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'compensation_requested';"
    )
    _execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'compensation_planned';"
    )
    _execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'compensation_failed';"
    )

    op.add_column(
        "ops_workflow_workflow_event",
        sa.Column("event_seq", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_workflow_workflow_transition",
        sa.Column(
            "compensation_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        schema=_SCHEMA,
    )

    _execute("""
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY tenant_id, workflow_instance_id
                    ORDER BY occurred_at ASC, id ASC
                ) AS rn
            FROM mugen.ops_workflow_workflow_event
        )
        UPDATE mugen.ops_workflow_workflow_event e
           SET event_seq = ranked.rn
          FROM ranked
         WHERE e.id = ranked.id
           AND e.event_seq IS NULL;
        """)

    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_event_seq"),
        "ops_workflow_workflow_event",
        ["event_seq"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_wf_event_event_seq_positive_if_set",
        "ops_workflow_workflow_event",
        "event_seq IS NULL OR event_seq > 0",
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_ops_wf_event_tenant_instance_event_seq",
        "ops_workflow_workflow_event",
        ["tenant_id", "workflow_instance_id", "event_seq"],
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_action_dedup",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=_sql_text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=_sql_text("1"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=False),
        sa.Column("action_name", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("client_action_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("request_hash", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("response_code", sa.BigInteger(), nullable=True),
        sa.Column(
            "response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_actor_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_action_dedup_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["last_actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_action_dedup_last_actor",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                f"{_SCHEMA}.ops_workflow_workflow_instance.tenant_id",
                f"{_SCHEMA}.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_action_dedup_tenant_instance",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(action_name)) > 0",
            name="ck_ops_wf_action_dedup_action_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(client_action_key)) > 0",
            name="ck_ops_wf_action_dedup_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(request_hash)) > 0",
            name="ck_ops_wf_action_dedup_hash_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_action_dedup"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_action_dedup_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_instance_id",
            "action_name",
            "client_action_key",
            name="ux_ops_wf_action_dedup_instance_action_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_action_dedup_workflow_instance_id"),
        "ops_workflow_action_dedup",
        ["workflow_instance_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_action_dedup_action_name"),
        "ops_workflow_action_dedup",
        ["action_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_action_dedup_client_action_key"),
        "ops_workflow_action_dedup",
        ["client_action_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_action_dedup_completed_at"),
        "ops_workflow_action_dedup",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_action_dedup_last_actor_user_id"),
        "ops_workflow_action_dedup",
        ["last_actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_action_dedup_tenant_instance_completed",
        "ops_workflow_action_dedup",
        ["tenant_id", "workflow_instance_id", "completed_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_wf_action_dedup_tenant_instance_completed",
        table_name="ops_workflow_action_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_action_dedup_last_actor_user_id"),
        table_name="ops_workflow_action_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_action_dedup_completed_at"),
        table_name="ops_workflow_action_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_action_dedup_client_action_key"),
        table_name="ops_workflow_action_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_action_dedup_action_name"),
        table_name="ops_workflow_action_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_action_dedup_workflow_instance_id"),
        table_name="ops_workflow_action_dedup",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_action_dedup", schema=_SCHEMA)

    op.drop_constraint(
        "ux_ops_wf_event_tenant_instance_event_seq",
        "ops_workflow_workflow_event",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "ck_ops_wf_event_event_seq_positive_if_set",
        "ops_workflow_workflow_event",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_event_seq"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )

    op.drop_column(
        "ops_workflow_workflow_transition",
        "compensation_json",
        schema=_SCHEMA,
    )
    op.drop_column(
        "ops_workflow_workflow_event",
        "event_seq",
        schema=_SCHEMA,
    )

    # PostgreSQL enum labels are additive; downgrade intentionally leaves labels.
