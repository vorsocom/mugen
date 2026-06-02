"""human handoff sessions

Revision ID: fd4e1b2c3a9d
Revises: fc2b4d6e8a1c
Create Date: 2026-06-01 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fd4e1b2c3a9d"
down_revision: Union[str, Sequence[str], None] = "fc2b4d6e8a1c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.create_table(
        "channel_orchestration_human_handoff_session",
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
        sa.Column("scope_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("platform", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("channel_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("room_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("sender_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("conversation_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("client_profile_id", sa.Uuid(), nullable=True),
        sa.Column("service_route_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("deactivation_reason", sa.String(length=1024), nullable=True),
        sa.Column("last_human_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_status", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("last_delivery_error", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_handoff_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["client_profile_id"],
            [f"{_SCHEMA}.admin_messaging_client_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_handoff_client_profile",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_handoff_owner",
        ),
        sa.ForeignKeyConstraint(
            ["deactivated_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_handoff_deactivated_by",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_chorch_handoff__scope_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_chorch_handoff__platform_nonempty",
        ),
        sa.CheckConstraint(
            "channel_id IS NULL OR length(btrim(channel_id)) > 0",
            name="ck_chorch_handoff__channel_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "room_id IS NULL OR length(btrim(room_id)) > 0",
            name="ck_chorch_handoff__room_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "sender_id IS NULL OR length(btrim(sender_id)) > 0",
            name="ck_chorch_handoff__sender_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "conversation_id IS NULL OR length(btrim(conversation_id)) > 0",
            name="ck_chorch_handoff__conversation_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
            name="ck_chorch_handoff__service_route_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_chorch_handoff__status_nonempty",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_chorch_handoff__reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "deactivation_reason IS NULL OR "
                "length(btrim(deactivation_reason)) > 0"
            ),
            name="ck_chorch_handoff__deactivation_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "last_delivery_status IS NULL OR "
                "length(btrim(last_delivery_status)) > 0"
            ),
            name="ck_chorch_handoff__delivery_status_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "last_delivery_error IS NULL OR "
                "length(btrim(last_delivery_error)) > 0"
            ),
            name="ck_chorch_handoff__delivery_error_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_handoff"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_handoff__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_chorch_handoff__tenant_scope_active",
        "channel_orchestration_human_handoff_session",
        ["tenant_id", "scope_key"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_chorch_handoff__tenant_status_updated",
        "channel_orchestration_human_handoff_session",
        ["tenant_id", "status", "updated_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_handoff__tenant_platform_sender",
        "channel_orchestration_human_handoff_session",
        ["tenant_id", "platform", "sender_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_handoff__tenant_client_profile",
        "channel_orchestration_human_handoff_session",
        ["tenant_id", "client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chorch_handoff__tenant_client_profile",
        table_name="channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_handoff__tenant_platform_sender",
        table_name="channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_handoff__tenant_status_updated",
        table_name="channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_chorch_handoff__tenant_scope_active",
        table_name="channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_human_handoff_session", schema=_SCHEMA)
