"""channel_orchestration initial schema

Revision ID: d4c3b2a1f0e9
Revises: c2e4f6a8d0b2
Create Date: 2026-02-14 13:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "d4c3b2a1f0e9"
down_revision: Union[str, None] = "c2e4f6a8d0b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    op.create_table(
        "channel_orchestration_orchestration_policy",
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
        sa.Column(
            "hours_mode",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'always_on'"),
        ),
        sa.Column(
            "escalation_mode",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'manual'"),
        ),
        sa.Column(
            "fallback_policy",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'default_route'"),
        ),
        sa.Column("fallback_target", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("escalation_target", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("escalation_after_seconds", sa.BigInteger(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_policy_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_chorch_policy__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_chorch_policy__name_nonempty",
        ),
        sa.CheckConstraint(
            "escalation_after_seconds IS NULL OR escalation_after_seconds >= 0",
            name="ck_chorch_policy__escalation_after_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_policy"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_chorch_policy__tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_chorch_policy__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_policy__tenant_active",
        "channel_orchestration_orchestration_policy",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_channel_profile",
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
        sa.Column("channel_key", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("route_default_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_profile_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            [f"{_SCHEMA}.channel_orchestration_orchestration_policy.id"],
            ondelete="SET NULL",
            name="fk_chorch_profile_policy",
        ),
        sa.CheckConstraint(
            "length(btrim(channel_key)) > 0",
            name="ck_chorch_profile__channel_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(profile_key)) > 0",
            name="ck_chorch_profile__profile_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_profile"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_chorch_profile__tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_key",
            "profile_key",
            name="ux_chorch_profile__tenant_channel_profile",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_profile__tenant_channel_active",
        "channel_orchestration_channel_profile",
        ["tenant_id", "channel_key", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_intake_rule",
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
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("match_kind", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("match_value", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("route_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "priority",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_intake_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_intake_profile",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_chorch_intake_rule__name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(match_kind)) > 0",
            name="ck_chorch_intake_rule__kind_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(match_value)) > 0",
            name="ck_chorch_intake_rule__value_nonempty",
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name="ck_chorch_intake_rule__priority_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_intake"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_intake_rule__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_profile_id",
            "name",
            name="ux_chorch_intake_rule__tenant_profile_name",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_intake_rule__tenant_profile_kind_priority",
        "channel_orchestration_intake_rule",
        ["tenant_id", "channel_profile_id", "match_kind", "priority"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_routing_rule",
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
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("route_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("target_queue_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_service_key", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("target_namespace", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "priority",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_routing_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_routing_profile",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_routing_owner",
        ),
        sa.CheckConstraint(
            "length(btrim(route_key)) > 0",
            name="ck_chorch_routing_rule__route_nonempty",
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name="ck_chorch_routing_rule__priority_nonnegative",
        ),
        sa.CheckConstraint(
            (
                "target_queue_name IS NOT NULL OR owner_user_id IS NOT NULL OR "
                "target_service_key IS NOT NULL"
            ),
            name="ck_chorch_routing_rule__target_required",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_routing"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_routing_rule__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_routing_rule__tenant_profile_route_active",
        "channel_orchestration_routing_rule",
        ["tenant_id", "channel_profile_id", "route_key", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_throttle_rule",
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
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "sender_scope",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'sender'"),
        ),
        sa.Column(
            "window_seconds",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("60"),
        ),
        sa.Column(
            "max_messages",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("20"),
        ),
        sa.Column(
            "block_on_violation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("block_duration_seconds", sa.BigInteger(), nullable=True),
        sa.Column(
            "priority",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("100"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_throttle_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_throttle_profile",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_chorch_throttle__code_nonempty",
        ),
        sa.CheckConstraint(
            "window_seconds > 0",
            name="ck_chorch_throttle__window_positive",
        ),
        sa.CheckConstraint(
            "max_messages > 0",
            name="ck_chorch_throttle__max_positive",
        ),
        sa.CheckConstraint(
            "priority >= 0",
            name="ck_chorch_throttle__priority_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_throttle"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_throttle__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_chorch_throttle__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_throttle__tenant_profile_active_priority",
        "channel_orchestration_throttle_rule",
        ["tenant_id", "channel_profile_id", "is_active", "priority"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_conversation_state",
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
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("sender_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "external_conversation_ref",
            postgresql.CITEXT(length=255),
            nullable=True,
        ),
        sa.Column(
            "status",
            postgresql.CITEXT(length=64),
            nullable=False,
            server_default=sa.text("'open'"),
        ),
        sa.Column("route_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("assigned_queue_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("assigned_owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_service_key", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("last_intake_rule_id", sa.Uuid(), nullable=True),
        sa.Column("last_intake_result", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "escalation_level",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_escalated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_throttled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("throttled_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "window_message_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("fallback_mode", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("fallback_target", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("fallback_reason", sa.String(length=512), nullable=True),
        sa.Column(
            "is_fallback_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_state_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_state_profile",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            [f"{_SCHEMA}.channel_orchestration_orchestration_policy.id"],
            ondelete="SET NULL",
            name="fk_chorch_state_policy",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_owner_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_state_owner",
        ),
        sa.ForeignKeyConstraint(
            ["last_intake_rule_id"],
            [f"{_SCHEMA}.channel_orchestration_intake_rule.id"],
            ondelete="SET NULL",
            name="fk_chorch_state_last_intake",
        ),
        sa.CheckConstraint(
            "length(btrim(sender_key)) > 0",
            name="ck_chorch_state__sender_nonempty",
        ),
        sa.CheckConstraint(
            "escalation_level >= 0",
            name="ck_chorch_state__escalation_level_nonnegative",
        ),
        sa.CheckConstraint(
            "window_message_count >= 0",
            name="ck_chorch_state__window_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_state"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_state__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_state__tenant_sender_status",
        "channel_orchestration_conversation_state",
        ["tenant_id", "sender_key", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_blocklist_entry",
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
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("sender_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column(
            "blocked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("blocked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("unblocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unblocked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("unblock_reason", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_blocklist_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_blocklist_profile",
        ),
        sa.ForeignKeyConstraint(
            ["blocked_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_blocklist_blocked_by",
        ),
        sa.ForeignKeyConstraint(
            ["unblocked_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_blocklist_unblocked_by",
        ),
        sa.CheckConstraint(
            "length(btrim(sender_key)) > 0",
            name="ck_chorch_blocklist__sender_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_blocklist"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_blocklist__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "channel_profile_id",
            "sender_key",
            "is_active",
            name="ux_chorch_blocklist__tenant_profile_sender_active",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_blocklist__tenant_sender_active_expiry",
        "channel_orchestration_blocklist_entry",
        ["tenant_id", "sender_key", "is_active", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "channel_orchestration_orchestration_event",
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
        sa.Column("conversation_state_id", sa.Uuid(), nullable=True),
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("sender_key", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("decision", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("source", postgresql.CITEXT(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_event_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_state_id"],
            [f"{_SCHEMA}.channel_orchestration_conversation_state.id"],
            ondelete="SET NULL",
            name="fk_chorch_event_state",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_event_profile",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_chorch_event_actor",
        ),
        sa.CheckConstraint(
            "event_type IS NOT NULL AND length(btrim(event_type)) > 0",
            name="ck_chorch_event__type_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_event"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_event__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_event__tenant_conversation_occurred",
        "channel_orchestration_orchestration_event",
        ["tenant_id", "conversation_state_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chorch_event__tenant_conversation_occurred",
        table_name="channel_orchestration_orchestration_event",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_orchestration_event", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_blocklist__tenant_sender_active_expiry",
        table_name="channel_orchestration_blocklist_entry",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_blocklist_entry", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_state__tenant_sender_status",
        table_name="channel_orchestration_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_conversation_state", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_throttle__tenant_profile_active_priority",
        table_name="channel_orchestration_throttle_rule",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_throttle_rule", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_routing_rule__tenant_profile_route_active",
        table_name="channel_orchestration_routing_rule",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_routing_rule", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_intake_rule__tenant_profile_kind_priority",
        table_name="channel_orchestration_intake_rule",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_intake_rule", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_profile__tenant_channel_active",
        table_name="channel_orchestration_channel_profile",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_channel_profile", schema=_SCHEMA)

    op.drop_index(
        "ix_chorch_policy__tenant_active",
        table_name="channel_orchestration_orchestration_policy",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_orchestration_policy", schema=_SCHEMA)
