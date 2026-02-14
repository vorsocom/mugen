"""audit events append-only

Revision ID: 8f0c1d2e3a4b
Revises: f7b1c2d3e4a5
Create Date: 2026-02-11 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "8f0c1d2e3a4b"
down_revision: Union[str, None] = "f7b1c2d3e4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    op.create_table(
        "audit_event",
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
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("entity_set", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("entity", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("operation", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("action_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("outcome", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("request_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("correlation_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("source_plugin", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("changed_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("before_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redaction_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redaction_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.CheckConstraint(
            "length(btrim(entity_set)) > 0",
            name="ck_audit_event__entity_set_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(entity)) > 0",
            name="ck_audit_event__entity_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(operation)) > 0",
            name="ck_audit_event__operation_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(outcome)) > 0",
            name="ck_audit_event__outcome_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_plugin)) > 0",
            name="ck_audit_event__source_plugin_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_event"),
        schema=_SCHEMA,
    )

    op.create_index(
        op.f("ix_mugen_audit_event_tenant_id"),
        "audit_event",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_actor_id"),
        "audit_event",
        ["actor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_entity_set"),
        "audit_event",
        ["entity_set"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_entity"),
        "audit_event",
        ["entity"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_entity_id"),
        "audit_event",
        ["entity_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_operation"),
        "audit_event",
        ["operation"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_action_name"),
        "audit_event",
        ["action_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_occurred_at"),
        "audit_event",
        ["occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_outcome"),
        "audit_event",
        ["outcome"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_request_id"),
        "audit_event",
        ["request_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_correlation_id"),
        "audit_event",
        ["correlation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_source_plugin"),
        "audit_event",
        ["source_plugin"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_retention_until"),
        "audit_event",
        ["retention_until"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_redaction_due_at"),
        "audit_event",
        ["redaction_due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_redacted_at"),
        "audit_event",
        ["redacted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_event__entity_lookup",
        "audit_event",
        ["entity_set", "entity_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )

def downgrade() -> None:
    op.drop_index("ix_audit_event__entity_lookup", table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_redacted_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_redaction_due_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_retention_until"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_source_plugin"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_correlation_id"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_request_id"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_outcome"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_occurred_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_action_name"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_operation"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_entity_id"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_entity"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_entity_set"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_actor_id"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_tenant_id"), table_name="audit_event", schema=_SCHEMA)
    op.drop_table("audit_event", schema=_SCHEMA)
