"""ops_sla initial schema

Revision ID: a1c9d5e7f3b2
Revises: c13f8d2a7b9e
Create Date: 2026-02-13 16:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "a1c9d5e7f3b2"
down_revision: Union[str, None] = "c13f8d2a7b9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_sla_clock_status = postgresql.ENUM(
        "idle",
        "running",
        "paused",
        "stopped",
        "breached",
        name="ops_sla_clock_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_sla_breach_event_type = postgresql.ENUM(
        "breached",
        "escalated",
        "acknowledged",
        name="ops_sla_breach_event_type",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_sla_clock_status.create(bind, checkfirst=True)
    ops_sla_breach_event_type.create(bind, checkfirst=True)

    op.create_table(
        "ops_sla_calendar",
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
            "timezone",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column(
            "business_start_time",
            sa.Time(timezone=False),
            server_default=sa.text("'09:00:00'"),
            nullable=False,
        ),
        sa.Column(
            "business_end_time",
            sa.Time(timezone=False),
            server_default=sa.text("'17:00:00'"),
            nullable=False,
        ),
        sa.Column(
            "business_days",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[1,2,3,4,5]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "holiday_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
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
            name="fk_ops_sla_calendar__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_sla_calendar__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_calendar__name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(timezone)) > 0",
            name="ck_ops_sla_calendar__timezone_nonempty",
        ),
        sa.CheckConstraint(
            "business_start_time < business_end_time",
            name="ck_ops_sla_calendar__business_time_bounds",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_calendar"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_calendar__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_sla_calendar__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_calendar__tenant_active",
        "ops_sla_calendar",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_policy",
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
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
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
            name="fk_ops_sla_policy__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["mugen.ops_sla_calendar.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_policy__calendar_id__ops_sla_calendar",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_sla_policy__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_sla_policy__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_sla_policy__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_policy"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_ops_sla_policy__tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "code", name="ux_ops_sla_policy__tenant_code"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_policy__tenant_calendar",
        "ops_sla_policy",
        ["tenant_id", "calendar_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_target",
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
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("metric", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("priority", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("severity", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("target_minutes", sa.BigInteger(), nullable=False),
        sa.Column(
            "warn_before_minutes",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "auto_breach",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_target__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["mugen.ops_sla_policy.id"],
            ondelete="CASCADE",
            name="fk_ops_sla_target__policy_id__ops_sla_policy",
        ),
        sa.CheckConstraint(
            "length(btrim(metric)) > 0",
            name="ck_ops_sla_target__metric_nonempty",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR length(btrim(priority)) > 0",
            name="ck_ops_sla_target__priority_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "severity IS NULL OR length(btrim(severity)) > 0",
            name="ck_ops_sla_target__severity_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "target_minutes > 0",
            name="ck_ops_sla_target__target_minutes_positive",
        ),
        sa.CheckConstraint(
            "warn_before_minutes >= 0",
            name="ck_ops_sla_target__warn_before_minutes_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_target"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_ops_sla_target__tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "policy_id",
            "metric",
            "priority",
            "severity",
            name="ux_ops_sla_target__policy_metric_bucket",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_target__tenant_policy_metric",
        "ops_sla_target",
        ["tenant_id", "policy_id", "metric"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_clock",
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
        sa.Column("policy_id", sa.Uuid(), nullable=True),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("tracked_namespace", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("tracked_id", sa.Uuid(), nullable=True),
        sa.Column("tracked_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("metric", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("priority", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("severity", postgresql.CITEXT(length=32), nullable=True),
        sa.Column(
            "status",
            ops_sla_clock_status,
            server_default=sa.text("'idle'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "elapsed_seconds",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_breached",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "breach_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_clock__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["mugen.ops_sla_policy.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_clock__policy_id__ops_sla_policy",
        ),
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["mugen.ops_sla_calendar.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_clock__calendar_id__ops_sla_calendar",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["mugen.ops_sla_target.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_clock__target_id__ops_sla_target",
        ),
        sa.ForeignKeyConstraint(
            ["last_actor_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_clock__last_actor_uid__admin_user",
        ),
        sa.CheckConstraint(
            "length(btrim(tracked_namespace)) > 0",
            name="ck_ops_sla_clock__tracked_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "tracked_ref IS NULL OR length(btrim(tracked_ref)) > 0",
            name="ck_ops_sla_clock__tracked_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "tracked_id IS NOT NULL OR tracked_ref IS NOT NULL",
            name="ck_ops_sla_clock__tracked_target_required",
        ),
        sa.CheckConstraint(
            "length(btrim(metric)) > 0",
            name="ck_ops_sla_clock__metric_nonempty",
        ),
        sa.CheckConstraint(
            "priority IS NULL OR length(btrim(priority)) > 0",
            name="ck_ops_sla_clock__priority_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "severity IS NULL OR length(btrim(severity)) > 0",
            name="ck_ops_sla_clock__severity_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "elapsed_seconds >= 0",
            name="ck_ops_sla_clock__elapsed_seconds_nonnegative",
        ),
        sa.CheckConstraint(
            "breach_count >= 0",
            name="ck_ops_sla_clock__breach_count_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_clock"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_ops_sla_clock__tenant_id_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_clock__tenant_status_deadline",
        "ops_sla_clock",
        ["tenant_id", "status", "deadline_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_clock__tenant_tracking",
        "ops_sla_clock",
        ["tenant_id", "tracked_namespace", "metric", "tracked_id", "tracked_ref"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_sla_breach_event",
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
        sa.Column("event_type", ops_sla_breach_event_type, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "escalation_level",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("note", sa.String(length=2048), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_sla_breach_event__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_sla_breach_event__actor_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "clock_id"],
            ["mugen.ops_sla_clock.tenant_id", "mugen.ops_sla_clock.id"],
            ondelete="CASCADE",
            name="fkx_ops_sla_breach_event__tenant_clock",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_ops_sla_breach_event__reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_sla_breach_event__note_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "escalation_level >= 0",
            name="ck_ops_sla_breach_event__escalation_level_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_sla_breach_event"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_sla_breach_event__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_sla_breach_event__tenant_clock_occurred",
        "ops_sla_breach_event",
        ["tenant_id", "clock_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_sla_breach_event__tenant_clock_occurred",
        table_name="ops_sla_breach_event",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_breach_event", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_clock__tenant_tracking",
        table_name="ops_sla_clock",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_sla_clock__tenant_status_deadline",
        table_name="ops_sla_clock",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_clock", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_target__tenant_policy_metric",
        table_name="ops_sla_target",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_target", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_policy__tenant_calendar",
        table_name="ops_sla_policy",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_policy", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_sla_calendar__tenant_active",
        table_name="ops_sla_calendar",
        schema=_SCHEMA,
    )
    op.drop_table("ops_sla_calendar", schema=_SCHEMA)

    ops_sla_breach_event_type = postgresql.ENUM(
        name="ops_sla_breach_event_type",
        schema=_SCHEMA,
    )
    ops_sla_clock_status = postgresql.ENUM(
        name="ops_sla_clock_status",
        schema=_SCHEMA,
    )

    bind = op.get_bind()
    ops_sla_breach_event_type.drop(bind, checkfirst=True)
    ops_sla_clock_status.drop(bind, checkfirst=True)
