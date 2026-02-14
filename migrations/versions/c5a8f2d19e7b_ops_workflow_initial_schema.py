"""ops_workflow initial schema

Revision ID: c5a8f2d19e7b
Revises: a1c9d5e7f3b2
Create Date: 2026-02-13 16:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "c5a8f2d19e7b"
down_revision: Union[str, None] = "a1c9d5e7f3b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_workflow_version_status = postgresql.ENUM(
        "draft",
        "published",
        "retired",
        name="ops_workflow_version_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_workflow_instance_status = postgresql.ENUM(
        "draft",
        "active",
        "awaiting_approval",
        "completed",
        "cancelled",
        name="ops_workflow_instance_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_workflow_task_kind = postgresql.ENUM(
        "approval",
        "work_item",
        name="ops_workflow_task_kind",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_workflow_task_status = postgresql.ENUM(
        "open",
        "in_progress",
        "completed",
        "rejected",
        "cancelled",
        name="ops_workflow_task_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_workflow_event_type = postgresql.ENUM(
        "created",
        "started",
        "advanced",
        "approval_requested",
        "approved",
        "rejected",
        "task_assigned",
        "task_completed",
        "cancelled",
        name="ops_workflow_event_type",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_workflow_version_status.create(bind, checkfirst=True)
    ops_workflow_instance_status.create(bind, checkfirst=True)
    ops_workflow_task_kind.create(bind, checkfirst=True)
    ops_workflow_task_status.create(bind, checkfirst=True)
    ops_workflow_event_type.create(bind, checkfirst=True)

    op.create_table(
        "ops_workflow_workflow_definition",
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
        sa.Column("key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_def_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            ["mugen.admin_user.id"],
            name="fk_ops_wf_def_deleted_by",
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_wf_def_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_wf_def_name_nonempty",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_wf_def_soft_delete_consistent",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_def"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_def_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "key",
            name="ux_ops_wf_def_tenant_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_tenant_id"),
        "ops_workflow_workflow_definition",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_key"),
        "ops_workflow_workflow_definition",
        ["key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_is_active"),
        "ops_workflow_workflow_definition",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_deleted_at"),
        "ops_workflow_workflow_definition",
        ["deleted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_def_tenant_active",
        "ops_workflow_workflow_definition",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_workflow_version",
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
        sa.Column("workflow_definition_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            ops_workflow_version_status,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_ver_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_ver_published_by",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_definition_id"),
            (
                "mugen.ops_workflow_workflow_definition.tenant_id",
                "mugen.ops_workflow_workflow_definition.id",
            ),
            name="fkx_ops_wf_ver_tenant_definition",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_ops_wf_ver_version_number_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_ver"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_ver_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_definition_id",
            "version_number",
            name="ux_ops_wf_ver_tenant_def_version",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_version_tenant_id"),
        "ops_workflow_workflow_version",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_version_workflow_definition_id"),
        "ops_workflow_workflow_version",
        ["workflow_definition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_version_status"),
        "ops_workflow_workflow_version",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_version_published_by_user_id"),
        "ops_workflow_workflow_version",
        ["published_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_version_is_default"),
        "ops_workflow_workflow_version",
        ["is_default"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_ver_tenant_def_status",
        "ops_workflow_workflow_version",
        ["tenant_id", "workflow_definition_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_workflow_state",
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
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("key", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "is_initial",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_terminal",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_state_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_version_id"),
            (
                "mugen.ops_workflow_workflow_version.tenant_id",
                "mugen.ops_workflow_workflow_version.id",
            ),
            name="fkx_ops_wf_state_tenant_version",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_wf_state_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_wf_state_name_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_state"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_state_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_version_id",
            "key",
            name="ux_ops_wf_state_tenant_version_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_state_tenant_id"),
        "ops_workflow_workflow_state",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_state_workflow_version_id"),
        "ops_workflow_workflow_state",
        ["workflow_version_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_state_key"),
        "ops_workflow_workflow_state",
        ["key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_state_is_initial"),
        "ops_workflow_workflow_state",
        ["is_initial"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_state_is_terminal"),
        "ops_workflow_workflow_state",
        ["is_terminal"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_state_tenant_version_initial",
        "ops_workflow_workflow_state",
        ["tenant_id", "workflow_version_id", "is_initial"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_workflow_transition",
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
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("key", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("from_state_id", sa.Uuid(), nullable=False),
        sa.Column("to_state_id", sa.Uuid(), nullable=False),
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("auto_assign_user_id", sa.Uuid(), nullable=True),
        sa.Column("auto_assign_queue", postgresql.CITEXT(length=128), nullable=True),
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
            name="fk_ops_wf_transition_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["auto_assign_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_transition_auto_assign_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_version_id"),
            (
                "mugen.ops_workflow_workflow_version.tenant_id",
                "mugen.ops_workflow_workflow_version.id",
            ),
            name="fkx_ops_wf_transition_tenant_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "from_state_id"),
            (
                "mugen.ops_workflow_workflow_state.tenant_id",
                "mugen.ops_workflow_workflow_state.id",
            ),
            name="fkx_ops_wf_transition_tenant_from_state",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "to_state_id"),
            (
                "mugen.ops_workflow_workflow_state.tenant_id",
                "mugen.ops_workflow_workflow_state.id",
            ),
            name="fkx_ops_wf_transition_tenant_to_state",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_wf_transition_key_nonempty",
        ),
        sa.CheckConstraint(
            "from_state_id <> to_state_id",
            name="ck_ops_wf_transition_non_self_loop",
        ),
        sa.CheckConstraint(
            "auto_assign_queue IS NULL OR length(btrim(auto_assign_queue)) > 0",
            name="ck_ops_wf_transition_auto_queue_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_transition"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_transition_tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workflow_version_id",
            "key",
            name="ux_ops_wf_transition_tenant_version_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_tenant_id"),
        "ops_workflow_workflow_transition",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_workflow_version_id"),
        "ops_workflow_workflow_transition",
        ["workflow_version_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_key"),
        "ops_workflow_workflow_transition",
        ["key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_from_state_id"),
        "ops_workflow_workflow_transition",
        ["from_state_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_to_state_id"),
        "ops_workflow_workflow_transition",
        ["to_state_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_requires_approval"),
        "ops_workflow_workflow_transition",
        ["requires_approval"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_auto_assign_user_id"),
        "ops_workflow_workflow_transition",
        ["auto_assign_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_auto_assign_queue"),
        "ops_workflow_workflow_transition",
        ["auto_assign_queue"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_is_active"),
        "ops_workflow_workflow_transition",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_transition_tenant_from_state",
        "ops_workflow_workflow_transition",
        ["tenant_id", "from_state_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_workflow_instance",
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
        sa.Column("workflow_definition_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("current_state_id", sa.Uuid(), nullable=True),
        sa.Column("pending_transition_id", sa.Uuid(), nullable=True),
        sa.Column("pending_task_id", sa.Uuid(), nullable=True),
        sa.Column("title", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "status",
            ops_workflow_instance_status,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("subject_namespace", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("subject_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_instance_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["last_actor_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_instance_last_actor",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_definition_id"),
            (
                "mugen.ops_workflow_workflow_definition.tenant_id",
                "mugen.ops_workflow_workflow_definition.id",
            ),
            name="fkx_ops_wf_instance_tenant_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_version_id"),
            (
                "mugen.ops_workflow_workflow_version.tenant_id",
                "mugen.ops_workflow_workflow_version.id",
            ),
            name="fkx_ops_wf_instance_tenant_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "current_state_id"),
            (
                "mugen.ops_workflow_workflow_state.tenant_id",
                "mugen.ops_workflow_workflow_state.id",
            ),
            name="fkx_ops_wf_instance_tenant_current_state",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "pending_transition_id"),
            (
                "mugen.ops_workflow_workflow_transition.tenant_id",
                "mugen.ops_workflow_workflow_transition.id",
            ),
            name="fkx_ops_wf_instance_tenant_pending_transition",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "title IS NULL OR length(btrim(title)) > 0",
            name="ck_ops_wf_instance_title_nonempty",
        ),
        sa.CheckConstraint(
            "subject_namespace IS NULL OR length(btrim(subject_namespace)) > 0",
            name="ck_ops_wf_instance_subject_ns_nonempty",
        ),
        sa.CheckConstraint(
            "subject_ref IS NULL OR length(btrim(subject_ref)) > 0",
            name="ck_ops_wf_instance_subject_ref_nonempty",
        ),
        sa.CheckConstraint(
            "cancel_reason IS NULL OR length(btrim(cancel_reason)) > 0",
            name="ck_ops_wf_instance_cancel_reason_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_instance"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_instance_tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_tenant_id"),
        "ops_workflow_workflow_instance",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_workflow_definition_id"),
        "ops_workflow_workflow_instance",
        ["workflow_definition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_workflow_version_id"),
        "ops_workflow_workflow_instance",
        ["workflow_version_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_current_state_id"),
        "ops_workflow_workflow_instance",
        ["current_state_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_pending_transition_id"),
        "ops_workflow_workflow_instance",
        ["pending_transition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_pending_task_id"),
        "ops_workflow_workflow_instance",
        ["pending_task_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_external_ref"),
        "ops_workflow_workflow_instance",
        ["external_ref"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_status"),
        "ops_workflow_workflow_instance",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_subject_id"),
        "ops_workflow_workflow_instance",
        ["subject_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_started_at"),
        "ops_workflow_workflow_instance",
        ["started_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_completed_at"),
        "ops_workflow_workflow_instance",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_cancelled_at"),
        "ops_workflow_workflow_instance",
        ["cancelled_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_last_actor_user_id"),
        "ops_workflow_workflow_instance",
        ["last_actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_instance_tenant_status",
        "ops_workflow_workflow_instance",
        ["tenant_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_instance_tenant_version_state",
        "ops_workflow_workflow_instance",
        ["tenant_id", "workflow_version_id", "current_state_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_workflow_task",
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
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_transition_id", sa.Uuid(), nullable=True),
        sa.Column(
            "task_kind",
            ops_workflow_task_kind,
            server_default=sa.text("'work_item'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            ops_workflow_task_status,
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("title", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("queue_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "handoff_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_task_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_task_assignee",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_task_assigned_by",
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_task_completed_by",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_task_tenant_instance",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_transition_id"),
            (
                "mugen.ops_workflow_workflow_transition.tenant_id",
                "mugen.ops_workflow_workflow_transition.id",
            ),
            name="fkx_ops_wf_task_tenant_transition",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_ops_wf_task_title_nonempty",
        ),
        sa.CheckConstraint(
            "queue_name IS NULL OR length(btrim(queue_name)) > 0",
            name="ck_ops_wf_task_queue_nonempty",
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR length(btrim(outcome)) > 0",
            name="ck_ops_wf_task_outcome_nonempty",
        ),
        sa.CheckConstraint(
            "handoff_count >= 0",
            name="ck_ops_wf_task_handoff_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_task"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_task_tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_tenant_id"),
        "ops_workflow_workflow_task",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_workflow_instance_id"),
        "ops_workflow_workflow_task",
        ["workflow_instance_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_workflow_transition_id"),
        "ops_workflow_workflow_task",
        ["workflow_transition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_task_kind"),
        "ops_workflow_workflow_task",
        ["task_kind"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_status"),
        "ops_workflow_workflow_task",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_assignee_user_id"),
        "ops_workflow_workflow_task",
        ["assignee_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_queue_name"),
        "ops_workflow_workflow_task",
        ["queue_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_assigned_by_user_id"),
        "ops_workflow_workflow_task",
        ["assigned_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_assigned_at"),
        "ops_workflow_workflow_task",
        ["assigned_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_completed_at"),
        "ops_workflow_workflow_task",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_cancelled_at"),
        "ops_workflow_workflow_task",
        ["cancelled_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_task_completed_by_user_id"),
        "ops_workflow_workflow_task",
        ["completed_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_task_tenant_instance_status",
        "ops_workflow_workflow_task",
        ["tenant_id", "workflow_instance_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_workflow_workflow_event",
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
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_task_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", ops_workflow_event_type, nullable=False),
        sa.Column("from_state_id", sa.Uuid(), nullable=True),
        sa.Column("to_state_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=2048), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_wf_event_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_wf_event_actor_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_instance_id"),
            (
                "mugen.ops_workflow_workflow_instance.tenant_id",
                "mugen.ops_workflow_workflow_instance.id",
            ),
            name="fkx_ops_wf_event_tenant_instance",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "workflow_task_id"),
            (
                "mugen.ops_workflow_workflow_task.tenant_id",
                "mugen.ops_workflow_workflow_task.id",
            ),
            name="fkx_ops_wf_event_tenant_task",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_wf_event_note_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_wf_event"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_wf_event_tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_tenant_id"),
        "ops_workflow_workflow_event",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_workflow_instance_id"),
        "ops_workflow_workflow_event",
        ["workflow_instance_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_workflow_task_id"),
        "ops_workflow_workflow_event",
        ["workflow_task_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_event_type"),
        "ops_workflow_workflow_event",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_actor_user_id"),
        "ops_workflow_workflow_event",
        ["actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_workflow_workflow_event_occurred_at"),
        "ops_workflow_workflow_event",
        ["occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_wf_event_tenant_instance_occ",
        "ops_workflow_workflow_event",
        ["tenant_id", "workflow_instance_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_wf_event_tenant_instance_occ",
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_occurred_at"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_actor_user_id"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_event_type"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_workflow_task_id"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_workflow_instance_id"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_event_tenant_id"),
        table_name="ops_workflow_workflow_event",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_event", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_task_tenant_instance_status",
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_completed_by_user_id"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_cancelled_at"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_completed_at"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_assigned_at"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_assigned_by_user_id"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_queue_name"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_assignee_user_id"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_status"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_task_kind"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_workflow_transition_id"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_workflow_instance_id"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_task_tenant_id"),
        table_name="ops_workflow_workflow_task",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_task", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_instance_tenant_version_state",
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_wf_instance_tenant_status",
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_last_actor_user_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_cancelled_at"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_completed_at"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_started_at"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_subject_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_status"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_external_ref"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_pending_task_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_pending_transition_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_current_state_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_workflow_version_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_workflow_definition_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_instance_tenant_id"),
        table_name="ops_workflow_workflow_instance",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_instance", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_transition_tenant_from_state",
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_is_active"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_auto_assign_queue"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_auto_assign_user_id"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_requires_approval"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_to_state_id"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_from_state_id"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_key"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_workflow_version_id"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_transition_tenant_id"),
        table_name="ops_workflow_workflow_transition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_transition", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_state_tenant_version_initial",
        table_name="ops_workflow_workflow_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_state_is_terminal"),
        table_name="ops_workflow_workflow_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_state_is_initial"),
        table_name="ops_workflow_workflow_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_state_key"),
        table_name="ops_workflow_workflow_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_state_workflow_version_id"),
        table_name="ops_workflow_workflow_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_state_tenant_id"),
        table_name="ops_workflow_workflow_state",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_state", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_ver_tenant_def_status",
        table_name="ops_workflow_workflow_version",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_version_is_default"),
        table_name="ops_workflow_workflow_version",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_version_published_by_user_id"),
        table_name="ops_workflow_workflow_version",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_version_status"),
        table_name="ops_workflow_workflow_version",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_version_workflow_definition_id"),
        table_name="ops_workflow_workflow_version",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_version_tenant_id"),
        table_name="ops_workflow_workflow_version",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_version", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_wf_def_tenant_active",
        table_name="ops_workflow_workflow_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_deleted_at"),
        table_name="ops_workflow_workflow_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_is_active"),
        table_name="ops_workflow_workflow_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_key"),
        table_name="ops_workflow_workflow_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_workflow_workflow_definition_tenant_id"),
        table_name="ops_workflow_workflow_definition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_workflow_workflow_definition", schema=_SCHEMA)

    postgresql.ENUM(
        "created",
        "started",
        "advanced",
        "approval_requested",
        "approved",
        "rejected",
        "task_assigned",
        "task_completed",
        "cancelled",
        name="ops_workflow_event_type",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "open",
        "in_progress",
        "completed",
        "rejected",
        "cancelled",
        name="ops_workflow_task_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "approval",
        "work_item",
        name="ops_workflow_task_kind",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "draft",
        "active",
        "awaiting_approval",
        "completed",
        "cancelled",
        name="ops_workflow_instance_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "draft",
        "published",
        "retired",
        name="ops_workflow_version_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
