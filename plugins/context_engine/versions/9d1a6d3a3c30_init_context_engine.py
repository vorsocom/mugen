"""init context engine

Revision ID: 9d1a6d3a3c30
Revises:
Create Date: 2026-03-06 14:20:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9d1a6d3a3c30"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
        sa.ForeignKey("mugen.admin_tenant.id", ondelete="RESTRICT"),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "context_engine_context_policy",
        *_base_columns(),
        _tenant_column(),
        sa.Column("policy_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("budget_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "redaction_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "retention_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "contributor_allow",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "contributor_deny",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "source_allow",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "source_deny",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "trace_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "cache_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "policy_key",
            name="ux_ctxeng_policy__tenant_key",
        ),
        sa.CheckConstraint(
            "length(btrim(policy_key)) > 0",
            name="ck_ctxeng_policy__policy_key",
        ),
    )
    op.create_index(
        "ix_context_engine_context_policy_tenant_id",
        "context_engine_context_policy",
        ["tenant_id"],
    )
    op.create_index(
        "ix_context_engine_context_policy_is_active",
        "context_engine_context_policy",
        ["is_active"],
    )

    op.create_table(
        "context_engine_context_profile",
        *_base_columns(),
        _tenant_column(),
        sa.Column("name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("platform", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("channel_key", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "policy_id",
            sa.Uuid(),
            sa.ForeignKey(
                "context_engine_context_policy.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="ux_ctxeng_profile__tenant_name",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ctxeng_profile__name",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_profile_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_profile_platform", ["platform"]),
        ("ix_context_engine_context_profile_channel_key", ["channel_key"]),
        ("ix_context_engine_context_profile_policy_id", ["policy_id"]),
        ("ix_context_engine_context_profile_is_active", ["is_active"]),
    ):
        op.create_index(index_name, "context_engine_context_profile", columns)

    op.create_table(
        "context_engine_context_contributor_binding",
        *_base_columns(),
        _tenant_column(),
        sa.Column("binding_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("contributor_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("platform", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("channel_key", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "priority",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "binding_key",
            name="ux_ctxeng_contributor_binding__tenant_key",
        ),
        sa.CheckConstraint(
            "length(btrim(binding_key)) > 0",
            name="ck_ctxeng_contributor_binding__binding_key",
        ),
        sa.CheckConstraint(
            "length(btrim(contributor_key)) > 0",
            name="ck_ctxeng_contributor_binding__contributor_key",
        ),
    )
    for index_name, columns in (
        (
            "ix_context_engine_context_contributor_binding_tenant_id",
            ["tenant_id"],
        ),
        (
            "ix_context_engine_context_contributor_binding_contributor_key",
            ["contributor_key"],
        ),
        ("ix_context_engine_context_contributor_binding_platform", ["platform"]),
        (
            "ix_context_engine_context_contributor_binding_channel_key",
            ["channel_key"],
        ),
        ("ix_context_engine_context_contributor_binding_is_enabled", ["is_enabled"]),
    ):
        op.create_index(
            index_name,
            "context_engine_context_contributor_binding",
            columns,
        )

    op.create_table(
        "context_engine_context_source_binding",
        *_base_columns(),
        _tenant_column(),
        sa.Column("source_kind", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("source_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("platform", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("channel_key", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("locale", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("category", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "is_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "source_kind",
            "source_key",
            name="ux_ctxeng_source_binding__tenant_kind_key",
        ),
        sa.CheckConstraint(
            "length(btrim(source_kind)) > 0",
            name="ck_ctxeng_source_binding__source_kind",
        ),
        sa.CheckConstraint(
            "length(btrim(source_key)) > 0",
            name="ck_ctxeng_source_binding__source_key",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_source_binding_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_source_binding_source_kind", ["source_kind"]),
        ("ix_context_engine_context_source_binding_platform", ["platform"]),
        ("ix_context_engine_context_source_binding_channel_key", ["channel_key"]),
        ("ix_context_engine_context_source_binding_locale", ["locale"]),
        ("ix_context_engine_context_source_binding_category", ["category"]),
        ("ix_context_engine_context_source_binding_is_enabled", ["is_enabled"]),
    ):
        op.create_index(index_name, "context_engine_context_source_binding", columns)

    op.create_table(
        "context_engine_context_trace_policy",
        *_base_columns(),
        _tenant_column(),
        sa.Column("name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "capture_prepare",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "capture_commit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "capture_selected_items",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "capture_dropped_items",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name="ux_ctxeng_trace_policy__tenant_name",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ctxeng_trace_policy__name",
        ),
    )
    op.create_index(
        "ix_context_engine_context_trace_policy_tenant_id",
        "context_engine_context_trace_policy",
        ["tenant_id"],
    )
    op.create_index(
        "ix_context_engine_context_trace_policy_is_active",
        "context_engine_context_trace_policy",
        ["is_active"],
    )

    op.create_table(
        "context_engine_context_state_snapshot",
        *_base_columns(),
        _tenant_column(),
        sa.Column("scope_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("platform", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("channel_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("room_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("sender_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("conversation_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("case_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("workflow_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("current_objective", sa.String(length=1024), nullable=True),
        sa.Column("entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "constraints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "unresolved_slots",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "commitments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "safety_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("routing", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.String(length=2048), nullable=True),
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("last_message_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("last_trace_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "scope_key",
            name="ux_ctxeng_state__tenant_scope",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_state__scope_key",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_state_snapshot_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_state_snapshot_platform", ["platform"]),
        ("ix_context_engine_context_state_snapshot_channel_id", ["channel_id"]),
        ("ix_context_engine_context_state_snapshot_room_id", ["room_id"]),
        ("ix_context_engine_context_state_snapshot_sender_id", ["sender_id"]),
        (
            "ix_context_engine_context_state_snapshot_conversation_id",
            ["conversation_id"],
        ),
        ("ix_context_engine_context_state_snapshot_case_id", ["case_id"]),
        ("ix_context_engine_context_state_snapshot_workflow_id", ["workflow_id"]),
    ):
        op.create_index(index_name, "context_engine_context_state_snapshot", columns)

    op.create_table(
        "context_engine_context_event_log",
        *_base_columns(),
        _tenant_column(),
        sa.Column("scope_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("sequence_no", sa.BigInteger(), nullable=False),
        sa.Column("role", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("message_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("trace_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("source", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "scope_key",
            "sequence_no",
            name="ux_ctxeng_event__tenant_scope_seq",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_event__scope_key",
        ),
        sa.CheckConstraint(
            "length(btrim(role)) > 0",
            name="ck_ctxeng_event__role",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_event_log_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_event_log_scope_key", ["scope_key"]),
        ("ix_context_engine_context_event_log_message_id", ["message_id"]),
        ("ix_context_engine_context_event_log_trace_id", ["trace_id"]),
        ("ix_context_engine_context_event_log_occurred_at", ["occurred_at"]),
    ):
        op.create_index(index_name, "context_engine_context_event_log", columns)
    op.create_index(
        "ix_ctxeng_event__tenant_scope_occurred",
        "context_engine_context_event_log",
        ["tenant_id", "scope_key", "occurred_at"],
    )

    op.create_table(
        "context_engine_context_memory_record",
        *_base_columns(),
        _tenant_column(),
        sa.Column(
            "scope_partition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("memory_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("memory_key", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("subject", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("commit_token", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "length(btrim(memory_type)) > 0",
            name="ck_ctxeng_memory__memory_type",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_memory_record_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_memory_record_memory_type", ["memory_type"]),
        ("ix_context_engine_context_memory_record_memory_key", ["memory_key"]),
        ("ix_context_engine_context_memory_record_subject", ["subject"]),
        ("ix_context_engine_context_memory_record_expires_at", ["expires_at"]),
        ("ix_context_engine_context_memory_record_is_deleted", ["is_deleted"]),
    ):
        op.create_index(index_name, "context_engine_context_memory_record", columns)

    op.create_table(
        "context_engine_context_cache_record",
        *_base_columns(),
        _tenant_column(),
        sa.Column("namespace", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("cache_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_hit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "hit_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "namespace",
            "cache_key",
            name="ux_ctxeng_cache__tenant_namespace_key",
        ),
        sa.CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_ctxeng_cache__namespace",
        ),
        sa.CheckConstraint(
            "length(btrim(cache_key)) > 0",
            name="ck_ctxeng_cache__cache_key",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_cache_record_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_cache_record_namespace", ["namespace"]),
        ("ix_context_engine_context_cache_record_expires_at", ["expires_at"]),
    ):
        op.create_index(index_name, "context_engine_context_cache_record", columns)

    op.create_table(
        "context_engine_context_trace",
        *_base_columns(),
        _tenant_column(),
        sa.Column("scope_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("trace_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("message_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("stage", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "selected_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "dropped_items",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_trace__scope_key",
        ),
        sa.CheckConstraint(
            "length(btrim(stage)) > 0",
            name="ck_ctxeng_trace__stage",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_trace_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_trace_scope_key", ["scope_key"]),
        ("ix_context_engine_context_trace_trace_id", ["trace_id"]),
        ("ix_context_engine_context_trace_message_id", ["message_id"]),
        ("ix_context_engine_context_trace_stage", ["stage"]),
        ("ix_context_engine_context_trace_occurred_at", ["occurred_at"]),
    ):
        op.create_index(index_name, "context_engine_context_trace", columns)
    op.create_index(
        "ix_ctxeng_trace__tenant_scope_occurred",
        "context_engine_context_trace",
        ["tenant_id", "scope_key", "occurred_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_ctxeng_trace__tenant_scope_occurred", table_name="context_engine_context_trace")
    for index_name in (
        "ix_context_engine_context_trace_occurred_at",
        "ix_context_engine_context_trace_stage",
        "ix_context_engine_context_trace_message_id",
        "ix_context_engine_context_trace_trace_id",
        "ix_context_engine_context_trace_scope_key",
        "ix_context_engine_context_trace_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_trace")
    op.drop_table("context_engine_context_trace")

    for index_name in (
        "ix_context_engine_context_cache_record_expires_at",
        "ix_context_engine_context_cache_record_namespace",
        "ix_context_engine_context_cache_record_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_cache_record")
    op.drop_table("context_engine_context_cache_record")

    for index_name in (
        "ix_context_engine_context_memory_record_is_deleted",
        "ix_context_engine_context_memory_record_expires_at",
        "ix_context_engine_context_memory_record_subject",
        "ix_context_engine_context_memory_record_memory_key",
        "ix_context_engine_context_memory_record_memory_type",
        "ix_context_engine_context_memory_record_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_memory_record")
    op.drop_table("context_engine_context_memory_record")

    op.drop_index("ix_ctxeng_event__tenant_scope_occurred", table_name="context_engine_context_event_log")
    for index_name in (
        "ix_context_engine_context_event_log_occurred_at",
        "ix_context_engine_context_event_log_trace_id",
        "ix_context_engine_context_event_log_message_id",
        "ix_context_engine_context_event_log_scope_key",
        "ix_context_engine_context_event_log_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_event_log")
    op.drop_table("context_engine_context_event_log")

    for index_name in (
        "ix_context_engine_context_state_snapshot_workflow_id",
        "ix_context_engine_context_state_snapshot_case_id",
        "ix_context_engine_context_state_snapshot_conversation_id",
        "ix_context_engine_context_state_snapshot_sender_id",
        "ix_context_engine_context_state_snapshot_room_id",
        "ix_context_engine_context_state_snapshot_channel_id",
        "ix_context_engine_context_state_snapshot_platform",
        "ix_context_engine_context_state_snapshot_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_state_snapshot")
    op.drop_table("context_engine_context_state_snapshot")

    for index_name in (
        "ix_context_engine_context_trace_policy_is_active",
        "ix_context_engine_context_trace_policy_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_trace_policy")
    op.drop_table("context_engine_context_trace_policy")

    for index_name in (
        "ix_context_engine_context_source_binding_is_enabled",
        "ix_context_engine_context_source_binding_category",
        "ix_context_engine_context_source_binding_locale",
        "ix_context_engine_context_source_binding_channel_key",
        "ix_context_engine_context_source_binding_platform",
        "ix_context_engine_context_source_binding_source_kind",
        "ix_context_engine_context_source_binding_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_source_binding")
    op.drop_table("context_engine_context_source_binding")

    for index_name in (
        "ix_context_engine_context_contributor_binding_is_enabled",
        "ix_context_engine_context_contributor_binding_channel_key",
        "ix_context_engine_context_contributor_binding_platform",
        "ix_context_engine_context_contributor_binding_contributor_key",
        "ix_context_engine_context_contributor_binding_tenant_id",
    ):
        op.drop_index(
            index_name,
            table_name="context_engine_context_contributor_binding",
        )
    op.drop_table("context_engine_context_contributor_binding")

    for index_name in (
        "ix_context_engine_context_profile_is_active",
        "ix_context_engine_context_profile_policy_id",
        "ix_context_engine_context_profile_channel_key",
        "ix_context_engine_context_profile_platform",
        "ix_context_engine_context_profile_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_profile")
    op.drop_table("context_engine_context_profile")

    for index_name in (
        "ix_context_engine_context_policy_is_active",
        "ix_context_engine_context_policy_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_policy")
    op.drop_table("context_engine_context_policy")
