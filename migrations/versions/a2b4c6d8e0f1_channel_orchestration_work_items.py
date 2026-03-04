"""channel orchestration work-item envelopes

Revision ID: a2b4c6d8e0f1
Revises: e7a1c2d3f4b5
Create Date: 2026-02-25 15:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "a2b4c6d8e0f1"
down_revision: Union[str, None] = "e7a1c2d3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.create_table(
        "channel_orchestration_work_item",
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
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("source", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "participants", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "attachments", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "extractions", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("linked_case_id", sa.Uuid(), nullable=True),
        sa.Column("linked_workflow_instance_id", sa.Uuid(), nullable=True),
        sa.Column(
            "replay_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_replayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_work_item__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["last_actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_work_item__last_actor_uid__admin_user",
        ),
        sa.CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_chorch_work_item__trace_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source)) > 0",
            name="ck_chorch_work_item__source_nonempty",
        ),
        sa.CheckConstraint(
            "replay_count >= 0",
            name="ck_chorch_work_item__replay_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_work_item"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_work_item__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "trace_id",
            name="ux_chorch_work_item__tenant_trace_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_work_item_trace_id"),
        "channel_orchestration_work_item",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_work_item_source"),
        "channel_orchestration_work_item",
        ["source"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_work_item_linked_case_id"),
        "channel_orchestration_work_item",
        ["linked_case_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_work_item_linked_workflow_instance_id"),
        "channel_orchestration_work_item",
        ["linked_workflow_instance_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_work_item_last_replayed_at"),
        "channel_orchestration_work_item",
        ["last_replayed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_work_item_last_actor_user_id"),
        "channel_orchestration_work_item",
        ["last_actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_work_item__tenant_source_created",
        "channel_orchestration_work_item",
        ["tenant_id", "source", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chorch_work_item__tenant_source_created",
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_work_item_last_actor_user_id"),
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_work_item_last_replayed_at"),
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_work_item_linked_workflow_instance_id"),
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_work_item_linked_case_id"),
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_work_item_source"),
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_work_item_trace_id"),
        table_name="channel_orchestration_work_item",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_work_item", schema=_SCHEMA)
