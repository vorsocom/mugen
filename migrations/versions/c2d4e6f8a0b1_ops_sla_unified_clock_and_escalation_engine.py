"""ops sla unified clock and escalation engine

Revision ID: c2d4e6f8a0b1
Revises: b2c4d6e8f0a1
Create Date: 2026-02-25 15:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "c2d4e6f8a0b1"
down_revision: Union[str, None] = "b2c4d6e8f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    ops_sla_clock_event_type = postgresql.ENUM(
        "warned",
        "breached",
        name="ops_sla_clock_event_type",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_sla_escalation_run_status = postgresql.ENUM(
        "ok",
        "partial",
        "failed",
        "noop",
        name="ops_sla_escalation_run_status",
        schema=_SCHEMA,
        create_type=False,
    )
    bind = op.get_bind()
    ops_sla_clock_event_type.create(bind, checkfirst=True)
    ops_sla_escalation_run_status.create(bind, checkfirst=True)

    op.create_table(
        "ops_sla_clock_definition",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("description", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column("metric", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("target_minutes", sa.BigInteger(), nullable=False),
        sa.Column(
            "warn_offsets_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_clock_definition__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_sla_clock_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_clock_definition__name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(metric)) > 0",
            name="ck_ops_sla_clock_definition__metric_nonempty",
        ),
        sa.CheckConstraint(
            "target_minutes > 0",
            name="ck_ops_sla_clock_definition__target_minutes_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_clock_definition"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_clock_definition__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_sla_clock_definition__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_definition_code"),
        "ops_sla_clock_definition",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_definition_metric"),
        "ops_sla_clock_definition",
        ["metric"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_definition_is_active"),
        "ops_sla_clock_definition",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_clock_definition__tenant_metric_active",
        "ops_sla_clock_definition",
        ["tenant_id", "metric", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.add_column(
        "ops_sla_clock",
        sa.Column("clock_definition_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_sla_clock",
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_sla_clock",
        sa.Column(
            "warned_offsets_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_ops_sla_clock__clock_definition_id__ops_sla_clock_definition",
        "ops_sla_clock",
        "ops_sla_clock_definition",
        ["clock_definition_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_clock_definition_id"),
        "ops_sla_clock",
        ["clock_definition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_trace_id"),
        "ops_sla_clock",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_sla_clock__trace_id_nonempty_if_set",
        "ops_sla_clock",
        "trace_id IS NULL OR length(btrim(trace_id)) > 0",
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_clock_event",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("clock_id", sa.Uuid(), nullable=False),
        sa.Column("clock_definition_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", ops_sla_clock_event_type, nullable=False),
        sa.Column("warned_offset_seconds", sa.BigInteger(), nullable=True),
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_clock_event__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_clock_event__actor_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "clock_id"),
            (
                "mugen.ops_sla_clock.tenant_id",
                "mugen.ops_sla_clock.id",
            ),
            ondelete="CASCADE",
            name="fkx_ops_sla_clock_event__tenant_clock",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "clock_definition_id"),
            (
                "mugen.ops_sla_clock_definition.tenant_id",
                "mugen.ops_sla_clock_definition.id",
            ),
            ondelete="SET NULL",
            name="fkx_ops_sla_clock_event__tenant_clock_definition",
        ),
        sa.CheckConstraint(
            "warned_offset_seconds IS NULL OR warned_offset_seconds >= 0",
            name="ck_ops_sla_clock_event__warned_offset_nonnegative_if_set",
        ),
        sa.CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_sla_clock_event__trace_id_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_clock_event"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_clock_event__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_event_clock_id"),
        "ops_sla_clock_event",
        ["clock_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_event_clock_definition_id"),
        "ops_sla_clock_event",
        ["clock_definition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_event_event_type"),
        "ops_sla_clock_event",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_event_trace_id"),
        "ops_sla_clock_event",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_event_occurred_at"),
        "ops_sla_clock_event",
        ["occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_clock_event_actor_user_id"),
        "ops_sla_clock_event",
        ["actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_clock_event__tenant_clock_occ",
        "ops_sla_clock_event",
        ["tenant_id", "clock_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_escalation_policy",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("policy_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("description", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column(
            "priority",
            sa.BigInteger(),
            server_default=sa.text("100"),
            nullable=False,
        ),
        sa.Column(
            "triggers_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "actions_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_escalation_policy__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(policy_key)) > 0",
            name="ck_ops_sla_escalation_policy__policy_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_escalation_policy__name_nonempty",
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name="ck_ops_sla_escalation_policy__priority_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_escalation_policy"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_escalation_policy__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "policy_key",
            name="ux_ops_sla_escalation_policy__tenant_policy_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_policy_policy_key"),
        "ops_sla_escalation_policy",
        ["policy_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_policy_is_active"),
        "ops_sla_escalation_policy",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_escalation_policy__tenant_active_priority",
        "ops_sla_escalation_policy",
        ["tenant_id", "is_active", "priority"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_escalation_run",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("escalation_policy_id", sa.Uuid(), nullable=False),
        sa.Column("clock_id", sa.Uuid(), nullable=True),
        sa.Column("clock_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            ops_sla_escalation_run_status,
            server_default=sa.text("'noop'"),
            nullable=False,
        ),
        sa.Column(
            "trigger_event_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("executed_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_escalation_run__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["executed_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_escalation_run__executed_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "escalation_policy_id"),
            (
                "mugen.ops_sla_escalation_policy.tenant_id",
                "mugen.ops_sla_escalation_policy.id",
            ),
            ondelete="CASCADE",
            name="fkx_ops_sla_escalation_run__tenant_policy",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "clock_id"),
            (
                "mugen.ops_sla_clock.tenant_id",
                "mugen.ops_sla_clock.id",
            ),
            ondelete="SET NULL",
            name="fkx_ops_sla_escalation_run__tenant_clock",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "clock_event_id"),
            (
                "mugen.ops_sla_clock_event.tenant_id",
                "mugen.ops_sla_clock_event.id",
            ),
            ondelete="SET NULL",
            name="fkx_ops_sla_escalation_run__tenant_clock_event",
        ),
        sa.CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_sla_escalation_run__trace_id_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_escalation_run"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_escalation_run__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_escalation_policy_id"),
        "ops_sla_escalation_run",
        ["escalation_policy_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_clock_id"),
        "ops_sla_escalation_run",
        ["clock_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_clock_event_id"),
        "ops_sla_escalation_run",
        ["clock_event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_status"),
        "ops_sla_escalation_run",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_trace_id"),
        "ops_sla_escalation_run",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_executed_at"),
        "ops_sla_escalation_run",
        ["executed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_sla_escalation_run_executed_by_user_id"),
        "ops_sla_escalation_run",
        ["executed_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_escalation_run__tenant_policy_exec",
        "ops_sla_escalation_run",
        ["tenant_id", "escalation_policy_id", "executed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_escalation_run__tenant_status_exec",
        "ops_sla_escalation_run",
        ["tenant_id", "status", "executed_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_sla_escalation_run__tenant_status_exec",
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_sla_escalation_run__tenant_policy_exec",
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_executed_by_user_id"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_executed_at"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_trace_id"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_status"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_clock_event_id"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_clock_id"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_run_escalation_policy_id"),
        table_name="ops_sla_escalation_run",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_escalation_run", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_escalation_policy__tenant_active_priority",
        table_name="ops_sla_escalation_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_policy_is_active"),
        table_name="ops_sla_escalation_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_escalation_policy_policy_key"),
        table_name="ops_sla_escalation_policy",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_escalation_policy", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_clock_event__tenant_clock_occ",
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_event_actor_user_id"),
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_event_occurred_at"),
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_event_trace_id"),
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_event_event_type"),
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_event_clock_definition_id"),
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_event_clock_id"),
        table_name="ops_sla_clock_event",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_clock_event", schema=_SCHEMA)

    op.drop_constraint(
        "ck_ops_sla_clock__trace_id_nonempty_if_set",
        "ops_sla_clock",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_trace_id"),
        table_name="ops_sla_clock",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_clock_definition_id"),
        table_name="ops_sla_clock",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "fk_ops_sla_clock__clock_definition_id__ops_sla_clock_definition",
        "ops_sla_clock",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("ops_sla_clock", "warned_offsets_json", schema=_SCHEMA)
    op.drop_column("ops_sla_clock", "trace_id", schema=_SCHEMA)
    op.drop_column("ops_sla_clock", "clock_definition_id", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_clock_definition__tenant_metric_active",
        table_name="ops_sla_clock_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_definition_is_active"),
        table_name="ops_sla_clock_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_definition_metric"),
        table_name="ops_sla_clock_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_sla_clock_definition_code"),
        table_name="ops_sla_clock_definition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_clock_definition", schema=_SCHEMA)

    ops_sla_escalation_run_status = postgresql.ENUM(
        name="ops_sla_escalation_run_status",
        schema=_SCHEMA,
    )
    ops_sla_clock_event_type = postgresql.ENUM(
        name="ops_sla_clock_event_type",
        schema=_SCHEMA,
    )
    bind = op.get_bind()
    ops_sla_escalation_run_status.drop(bind, checkfirst=True)
    ops_sla_clock_event_type.drop(bind, checkfirst=True)
