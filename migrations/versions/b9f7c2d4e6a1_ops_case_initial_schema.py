"""ops_case initial schema

Revision ID: b9f7c2d4e6a1
Revises: e1b2c3d4f5a6
Create Date: 2026-02-13 04:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "b9f7c2d4e6a1"
down_revision: Union[str, None] = "e1b2c3d4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_case_status = postgresql.ENUM(
        "new",
        "triaged",
        "in_progress",
        "waiting_external",
        "resolved",
        "closed",
        "cancelled",
        name="ops_case_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_case_priority = postgresql.ENUM(
        "low",
        "medium",
        "high",
        "urgent",
        name="ops_case_priority",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_case_severity = postgresql.ENUM(
        "low",
        "medium",
        "high",
        "critical",
        name="ops_case_severity",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_case_event_type = postgresql.ENUM(
        "created",
        "triaged",
        "assigned",
        "escalated",
        "resolved",
        "closed",
        "reopened",
        "cancelled",
        "note",
        name="ops_case_event_type",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_case_status.create(bind, checkfirst=True)
    ops_case_priority.create(bind, checkfirst=True)
    ops_case_severity.create(bind, checkfirst=True)
    ops_case_event_type.create(bind, checkfirst=True)

    op.create_table(
        "ops_case_case",
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
        sa.Column("case_number", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("title", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column(
            "status",
            ops_case_status,
            server_default=sa.text("'new'"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            ops_case_priority,
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            ops_case_severity,
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sla_target_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("queue_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "escalation_level",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "is_escalated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("escalated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("last_actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolution_summary", sa.String(length=2048), nullable=True),
        sa.Column("cancellation_reason", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_case_case__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case__owner_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["escalated_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case__escalated_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case__created_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["last_actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case__last_actor_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            name="fk_ops_case_case__deleted_by_uid__admin_user",
        ),
        sa.CheckConstraint(
            "length(btrim(case_number)) > 0",
            name="ck_ops_case_case__case_number_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_ops_case_case__title_nonempty",
        ),
        sa.CheckConstraint(
            "queue_name IS NULL OR length(btrim(queue_name)) > 0",
            name="ck_ops_case_case__queue_name_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "resolution_summary IS NULL OR length(btrim(resolution_summary)) > 0",
            name="ck_ops_case_case__resolution_summary_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "cancellation_reason IS NULL OR length(btrim(cancellation_reason)) > 0",
            name="ck_ops_case_case__cancellation_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "escalation_level >= 0",
            name="ck_ops_case_case__escalation_level_nonnegative",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_case_case__not_deleted_and_not_deleted_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_case_case"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "case_number",
            name="ux_ops_case_case__tenant_case_number",
        ),
        schema=_SCHEMA,
    )

    op.create_index(
        op.f("ix_mugen_ops_case_case_tenant_id"),
        "ops_case_case",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_case_number"),
        "ops_case_case",
        ["case_number"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_status"),
        "ops_case_case",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_priority"),
        "ops_case_case",
        ["priority"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_severity"),
        "ops_case_case",
        ["severity"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_due_at"),
        "ops_case_case",
        ["due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_sla_target_at"),
        "ops_case_case",
        ["sla_target_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_triaged_at"),
        "ops_case_case",
        ["triaged_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_escalated_at"),
        "ops_case_case",
        ["escalated_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_resolved_at"),
        "ops_case_case",
        ["resolved_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_closed_at"),
        "ops_case_case",
        ["closed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_cancelled_at"),
        "ops_case_case",
        ["cancelled_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_owner_user_id"),
        "ops_case_case",
        ["owner_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_queue_name"),
        "ops_case_case",
        ["queue_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_is_escalated"),
        "ops_case_case",
        ["is_escalated"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_escalated_by_user_id"),
        "ops_case_case",
        ["escalated_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_created_by_user_id"),
        "ops_case_case",
        ["created_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_last_actor_user_id"),
        "ops_case_case",
        ["last_actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_deleted_at"),
        "ops_case_case",
        ["deleted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_case_case__tenant_status_priority",
        "ops_case_case",
        ["tenant_id", "status", "priority"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_case_case__tenant_owner_queue",
        "ops_case_case",
        ["tenant_id", "owner_user_id", "queue_name"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_case_case_event",
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
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", ops_case_event_type, nullable=False),
        sa.Column("status_from", sa.String(length=64), nullable=True),
        sa.Column("status_to", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=2048), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_case_case_event__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case_event__actor_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "case_id"),
            (f"{_SCHEMA}.ops_case_case.tenant_id", f"{_SCHEMA}.ops_case_case.id"),
            name="fkx_ops_case_case_event__tenant_case",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_case_case_event__note_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_case_case_event"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case_event__tenant_id_id",
        ),
        schema=_SCHEMA,
    )

    op.create_index(
        op.f("ix_mugen_ops_case_case_event_tenant_id"),
        "ops_case_case_event",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_event_case_id"),
        "ops_case_case_event",
        ["case_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_event_event_type"),
        "ops_case_case_event",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_event_actor_user_id"),
        "ops_case_case_event",
        ["actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_event_occurred_at"),
        "ops_case_case_event",
        ["occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_case_case_event__tenant_case_occurred",
        "ops_case_case_event",
        ["tenant_id", "case_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_case_case_assignment",
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
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("queue_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_case_case_assignment__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case_assignment__owner_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case_assignment__assigned_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "case_id"),
            (f"{_SCHEMA}.ops_case_case.tenant_id", f"{_SCHEMA}.ops_case_case.id"),
            name="fkx_ops_case_case_assignment__tenant_case",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "queue_name IS NULL OR length(btrim(queue_name)) > 0",
            name="ck_ops_case_case_assignment__queue_name_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_ops_case_case_assignment__reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "NOT (is_active AND unassigned_at IS NOT NULL)",
            name="ck_ops_case_case_assignment__active_without_unassigned_at",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_case_case_assignment"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case_assignment__tenant_id_id",
        ),
        schema=_SCHEMA,
    )

    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_tenant_id"),
        "ops_case_case_assignment",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_case_id"),
        "ops_case_case_assignment",
        ["case_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_owner_user_id"),
        "ops_case_case_assignment",
        ["owner_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_queue_name"),
        "ops_case_case_assignment",
        ["queue_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_assigned_by_user_id"),
        "ops_case_case_assignment",
        ["assigned_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_assigned_at"),
        "ops_case_case_assignment",
        ["assigned_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_unassigned_at"),
        "ops_case_case_assignment",
        ["unassigned_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_assignment_is_active"),
        "ops_case_case_assignment",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_case_case_assignment__tenant_case_assigned",
        "ops_case_case_assignment",
        ["tenant_id", "case_id", "assigned_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_case_case_assignment__tenant_case_active",
        "ops_case_case_assignment",
        ["tenant_id", "case_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_case_case_link",
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
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("link_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("target_namespace", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("target_type", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("target_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("target_display", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "relationship_kind",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'related'"),
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_case_case_link__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_case_case_link__created_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            name="fk_ops_case_case_link__deleted_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "case_id"),
            (f"{_SCHEMA}.ops_case_case.tenant_id", f"{_SCHEMA}.ops_case_case.id"),
            name="fkx_ops_case_case_link__tenant_case",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(link_type)) > 0",
            name="ck_ops_case_case_link__link_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(target_type)) > 0",
            name="ck_ops_case_case_link__target_type_nonempty",
        ),
        sa.CheckConstraint(
            "target_ref IS NULL OR length(btrim(target_ref)) > 0",
            name="ck_ops_case_case_link__target_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "relationship_kind IS NULL OR length(btrim(relationship_kind)) > 0",
            name="ck_ops_case_case_link__relationship_kind_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "target_id IS NOT NULL OR target_ref IS NOT NULL",
            name="ck_ops_case_case_link__target_reference_required",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_case_case_link__not_deleted_and_not_deleted_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_case_case_link"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_case_case_link__tenant_id_id",
        ),
        schema=_SCHEMA,
    )

    op.create_index(
        op.f("ix_mugen_ops_case_case_link_tenant_id"),
        "ops_case_case_link",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_case_id"),
        "ops_case_case_link",
        ["case_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_link_type"),
        "ops_case_case_link",
        ["link_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_target_namespace"),
        "ops_case_case_link",
        ["target_namespace"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_target_type"),
        "ops_case_case_link",
        ["target_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_target_id"),
        "ops_case_case_link",
        ["target_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_target_ref"),
        "ops_case_case_link",
        ["target_ref"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_relationship_kind"),
        "ops_case_case_link",
        ["relationship_kind"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_created_by_user_id"),
        "ops_case_case_link",
        ["created_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_case_case_link_deleted_at"),
        "ops_case_case_link",
        ["deleted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_case_case_link__tenant_case_target",
        "ops_case_case_link",
        ["tenant_id", "case_id", "target_type", "target_id", "target_ref"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_case_case_link__tenant_case_target",
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_deleted_at"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_created_by_user_id"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_relationship_kind"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_target_ref"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_target_id"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_target_type"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_target_namespace"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_link_type"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_case_id"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_link_tenant_id"),
        table_name="ops_case_case_link",
        schema=_SCHEMA,
    )
    op.drop_table("ops_case_case_link", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_case_case_assignment__tenant_case_active",
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_case_case_assignment__tenant_case_assigned",
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_is_active"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_unassigned_at"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_assigned_at"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_assigned_by_user_id"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_queue_name"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_owner_user_id"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_case_id"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_assignment_tenant_id"),
        table_name="ops_case_case_assignment",
        schema=_SCHEMA,
    )
    op.drop_table("ops_case_case_assignment", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_case_case_event__tenant_case_occurred",
        table_name="ops_case_case_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_event_occurred_at"),
        table_name="ops_case_case_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_event_actor_user_id"),
        table_name="ops_case_case_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_event_event_type"),
        table_name="ops_case_case_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_event_case_id"),
        table_name="ops_case_case_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_event_tenant_id"),
        table_name="ops_case_case_event",
        schema=_SCHEMA,
    )
    op.drop_table("ops_case_case_event", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_case_case__tenant_owner_queue",
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_case_case__tenant_status_priority",
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_deleted_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_last_actor_user_id"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_created_by_user_id"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_escalated_by_user_id"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_is_escalated"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_queue_name"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_owner_user_id"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_cancelled_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_closed_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_resolved_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_escalated_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_triaged_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_sla_target_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_due_at"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_severity"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_priority"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_status"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_case_number"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_case_case_tenant_id"),
        table_name="ops_case_case",
        schema=_SCHEMA,
    )
    op.drop_table("ops_case_case", schema=_SCHEMA)

    postgresql.ENUM(
        "created",
        "triaged",
        "assigned",
        "escalated",
        "resolved",
        "closed",
        "reopened",
        "cancelled",
        "note",
        name="ops_case_event_type",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "low",
        "medium",
        "high",
        "critical",
        name="ops_case_severity",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "low",
        "medium",
        "high",
        "urgent",
        name="ops_case_priority",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "new",
        "triaged",
        "in_progress",
        "waiting_external",
        "resolved",
        "closed",
        "cancelled",
        name="ops_case_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)

