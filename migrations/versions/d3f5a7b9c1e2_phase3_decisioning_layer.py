"""phase3 decisioning layer for governance/workflow/sla

Revision ID: d3f5a7b9c1e2
Revises: c2d4e6f8a0b1
Create Date: 2026-02-25 16:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "d3f5a7b9c1e2"
down_revision: Union[str, None] = "c2d4e6f8a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'decision_opened';"
    )
    op.execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'decision_resolved';"
    )
    op.execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'decision_expired';"
    )
    op.execute(
        "ALTER TYPE mugen.ops_workflow_event_type "
        "ADD VALUE IF NOT EXISTS 'decision_cancelled';"
    )

    op.add_column(
        "ops_governance_policy_definition",
        sa.Column(
            "engine",
            postgresql.CITEXT(length=32),
            server_default=sa.text("'dsl'"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_governance_policy_definition",
        sa.Column(
            "document_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_gov_policy_definition__engine_nonempty",
        "ops_governance_policy_definition",
        "length(btrim(engine)) > 0",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_ops_gov_policy_definition__tenant_code",
        "ops_governance_policy_definition",
        schema=_SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_ops_gov_policy_definition__tenant_code_version",
        "ops_governance_policy_definition",
        ["tenant_id", "code", "version"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_ops_gov_policy_definition__tenant_code_active",
        "ops_governance_policy_definition",
        ["tenant_id", "code"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_active = true"),
    )

    op.add_column(
        "ops_governance_policy_decision_log",
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_governance_policy_decision_log",
        sa.Column("policy_key", postgresql.CITEXT(length=64), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_governance_policy_decision_log",
        sa.Column("policy_version", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_governance_policy_decision_log",
        sa.Column(
            "actor_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_governance_policy_decision_log",
        sa.Column(
            "input_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_governance_policy_decision_log",
        sa.Column(
            "decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_gov_policy_decision_log__trace_id_nonempty_if_set",
        "ops_governance_policy_decision_log",
        "trace_id IS NULL OR length(btrim(trace_id)) > 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_gov_policy_decision_log__policy_key_nonempty_if_set",
        "ops_governance_policy_decision_log",
        "policy_key IS NULL OR length(btrim(policy_key)) > 0",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__tenant_trace",
        "ops_governance_policy_decision_log",
        ["tenant_id", "trace_id"],
        unique=False,
        schema=_SCHEMA,
    )

    ops_wf_decision_request_status = postgresql.ENUM(
        "open",
        "resolved",
        "expired",
        "cancelled",
        name="ops_workflow_decision_request_status",
        schema=_SCHEMA,
        create_type=False,
    )
    bind = op.get_bind()
    ops_wf_decision_request_status.create(bind, checkfirst=True)

    op.create_table(
        "ops_workflow_decision_request",
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
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("template_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "status",
            ops_wf_decision_request_status,
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column(
            "requester_actor_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "assigned_to_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "options_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "context_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_task_id", sa.Uuid(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_decision_request_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_decision_request_tenant_instance",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_task_id"),
            (
                "mugen.ops_workflow_workflow_task.tenant_id",
                "mugen.ops_workflow_workflow_task.id",
            ),
            name="fkx_ops_wf_decision_request_tenant_task",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_wf_decision_request_trace_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(template_key)) > 0",
            name="ck_ops_wf_decision_request_template_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_decision_request"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_decision_request_tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_tenant_id"),
        "ops_workflow_decision_request",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_trace_id"),
        "ops_workflow_decision_request",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_template_key"),
        "ops_workflow_decision_request",
        ["template_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_status"),
        "ops_workflow_decision_request",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_workflow_instance_id"),
        "ops_workflow_decision_request",
        ["workflow_instance_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_workflow_task_id"),
        "ops_workflow_decision_request",
        ["workflow_task_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_due_at"),
        "ops_workflow_decision_request",
        ["due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_request_resolved_at"),
        "ops_workflow_decision_request",
        ["resolved_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_decision_request_tenant_status_due_at",
        "ops_workflow_decision_request",
        ["tenant_id", "status", "due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_decision_request_tenant_trace",
        "ops_workflow_decision_request",
        ["tenant_id", "trace_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_decision_outcome",
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
        sa.Column("decision_request_id", sa.Uuid(), nullable=False),
        sa.Column(
            "resolver_actor_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "outcome_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "signature_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_decision_outcome_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "decision_request_id"),
            (
                "mugen.ops_workflow_decision_request.tenant_id",
                "mugen.ops_workflow_decision_request.id",
            ),
            name="fkx_ops_wf_decision_outcome_tenant_request",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_decision_outcome"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_decision_outcome_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "decision_request_id",
            name="ux_ops_wf_decision_outcome_tenant_request",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_outcome_tenant_id"),
        "ops_workflow_decision_outcome",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_decision_outcome_decision_request_id"),
        "ops_workflow_decision_outcome",
        ["decision_request_id"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_outcome_decision_request_id"),
        table_name="ops_workflow_decision_outcome",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_outcome_tenant_id"),
        table_name="ops_workflow_decision_outcome",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_decision_outcome", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_decision_request_tenant_trace",
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_wf_decision_request_tenant_status_due_at",
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_resolved_at"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_due_at"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_workflow_task_id"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_workflow_instance_id"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_status"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_template_key"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_trace_id"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_decision_request_tenant_id"),
        table_name="ops_workflow_decision_request",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_decision_request", schema=_SCHEMA)

    postgresql.ENUM(
        name="ops_workflow_decision_request_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        "ix_ops_gov_policy_decision_log__tenant_trace",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_ops_gov_policy_decision_log__policy_key_nonempty_if_set",
        "ops_governance_policy_decision_log",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_ops_gov_policy_decision_log__trace_id_nonempty_if_set",
        "ops_governance_policy_decision_log",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column("ops_governance_policy_decision_log", "decision_json", schema=_SCHEMA)
    op.drop_column("ops_governance_policy_decision_log", "input_json", schema=_SCHEMA)
    op.drop_column("ops_governance_policy_decision_log", "actor_json", schema=_SCHEMA)
    op.drop_column(
        "ops_governance_policy_decision_log",
        "policy_version",
        schema=_SCHEMA,
    )
    op.drop_column("ops_governance_policy_decision_log", "policy_key", schema=_SCHEMA)
    op.drop_column("ops_governance_policy_decision_log", "trace_id", schema=_SCHEMA)

    op.drop_index(
        "ux_ops_gov_policy_definition__tenant_code_active",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_ops_gov_policy_definition__tenant_code_version",
        "ops_governance_policy_definition",
        schema=_SCHEMA,
        type_="unique",
    )
    op.create_unique_constraint(
        "ux_ops_gov_policy_definition__tenant_code",
        "ops_governance_policy_definition",
        ["tenant_id", "code"],
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_ops_gov_policy_definition__engine_nonempty",
        "ops_governance_policy_definition",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column("ops_governance_policy_definition", "document_json", schema=_SCHEMA)
    op.drop_column("ops_governance_policy_definition", "engine", schema=_SCHEMA)

    # PostgreSQL enum labels are additive; downgrade intentionally leaves labels.
