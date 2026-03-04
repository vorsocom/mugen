"""audit correlation and biz trace foundations

Revision ID: b8f2e6d4c1a9
Revises: a9e1d7c3b5f0
Create Date: 2026-02-25 10:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "b8f2e6d4c1a9"
down_revision: Union[str, Sequence[str], None] = "a9e1d7c3b5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.create_table(
        "audit_correlation_link",
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
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("correlation_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("request_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("source_plugin", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("entity_set", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("operation", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("action_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("parent_entity_set", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("parent_entity_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_audit_correlation_link__trace_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_plugin)) > 0",
            name="ck_audit_correlation_link__source_plugin_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(entity_set)) > 0",
            name="ck_audit_correlation_link__entity_set_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(operation)) > 0",
            name="ck_audit_correlation_link__operation_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_correlation_link"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_tenant_id"),
        "audit_correlation_link",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_trace_id"),
        "audit_correlation_link",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_correlation_id"),
        "audit_correlation_link",
        ["correlation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_request_id"),
        "audit_correlation_link",
        ["request_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_source_plugin"),
        "audit_correlation_link",
        ["source_plugin"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_entity_set"),
        "audit_correlation_link",
        ["entity_set"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_entity_id"),
        "audit_correlation_link",
        ["entity_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_operation"),
        "audit_correlation_link",
        ["operation"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_action_name"),
        "audit_correlation_link",
        ["action_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_correlation_link_occurred_at"),
        "audit_correlation_link",
        ["occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_correlation_link__trace_occurred",
        "audit_correlation_link",
        ["trace_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "audit_biz_trace_event",
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
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("span_id", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("parent_span_id", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("correlation_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("request_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("source_plugin", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("entity_set", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("action_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("stage", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_audit_biz_trace_event__trace_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_plugin)) > 0",
            name="ck_audit_biz_trace_event__source_plugin_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(stage)) > 0",
            name="ck_audit_biz_trace_event__stage_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_biz_trace_event"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_tenant_id"),
        "audit_biz_trace_event",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_trace_id"),
        "audit_biz_trace_event",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_span_id"),
        "audit_biz_trace_event",
        ["span_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_correlation_id"),
        "audit_biz_trace_event",
        ["correlation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_request_id"),
        "audit_biz_trace_event",
        ["request_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_source_plugin"),
        "audit_biz_trace_event",
        ["source_plugin"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_entity_set"),
        "audit_biz_trace_event",
        ["entity_set"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_action_name"),
        "audit_biz_trace_event",
        ["action_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_stage"),
        "audit_biz_trace_event",
        ["stage"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_biz_trace_event_occurred_at"),
        "audit_biz_trace_event",
        ["occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_biz_trace_event__trace_occurred",
        "audit_biz_trace_event",
        ["trace_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_audit_biz_trace_event__trace_occurred",
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_occurred_at"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_stage"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_action_name"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_entity_set"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_source_plugin"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_request_id"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_correlation_id"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_span_id"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_trace_id"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_biz_trace_event_tenant_id"),
        table_name="audit_biz_trace_event",
        schema=_SCHEMA,
    )
    op.drop_table("audit_biz_trace_event", schema=_SCHEMA)

    op.drop_index(
        "ix_audit_correlation_link__trace_occurred",
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_occurred_at"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_action_name"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_operation"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_entity_id"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_entity_set"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_source_plugin"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_request_id"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_correlation_id"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_trace_id"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_correlation_link_tenant_id"),
        table_name="audit_correlation_link",
        schema=_SCHEMA,
    )
    op.drop_table("audit_correlation_link", schema=_SCHEMA)
