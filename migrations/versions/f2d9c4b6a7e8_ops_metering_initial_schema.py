"""ops_metering initial schema

Revision ID: f2d9c4b6a7e8
Revises: c5a8f2d19e7b
Create Date: 2026-02-13 17:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "f2d9c4b6a7e8"
down_revision: Union[str, None] = "c5a8f2d19e7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_metering_meter_unit = postgresql.ENUM(
        "minute",
        "unit",
        "task",
        name="ops_metering_meter_unit",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_metering_aggregation_mode = postgresql.ENUM(
        "sum",
        "max",
        "latest",
        name="ops_metering_aggregation_mode",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_metering_rounding_mode = postgresql.ENUM(
        "none",
        "up",
        "down",
        "nearest",
        name="ops_metering_rounding_mode",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_metering_usage_session_status = postgresql.ENUM(
        "idle",
        "running",
        "paused",
        "stopped",
        name="ops_metering_usage_session_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_metering_usage_record_status = postgresql.ENUM(
        "recorded",
        "rated",
        "void",
        name="ops_metering_usage_record_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_metering_rated_usage_status = postgresql.ENUM(
        "rated",
        "void",
        name="ops_metering_rated_usage_status",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_metering_meter_unit.create(bind, checkfirst=True)
    ops_metering_aggregation_mode.create(bind, checkfirst=True)
    ops_metering_rounding_mode.create(bind, checkfirst=True)
    ops_metering_usage_session_status.create(bind, checkfirst=True)
    ops_metering_usage_record_status.create(bind, checkfirst=True)
    ops_metering_rated_usage_status.create(bind, checkfirst=True)

    op.create_table(
        "ops_metering_meter_definition",
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
        sa.Column(
            "unit",
            ops_metering_meter_unit,
            server_default=sa.text("'unit'"),
            nullable=False,
        ),
        sa.Column(
            "aggregation_mode",
            ops_metering_aggregation_mode,
            server_default=sa.text("'sum'"),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_metering_meter_definition__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_metering_meter_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_metering_meter_definition__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_metering_meter_definition"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_meter_definition__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_metering_meter_definition__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_metering_meter_definition__tenant_active",
        "ops_metering_meter_definition",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_metering_meter_policy",
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
        sa.Column("meter_definition_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("cap_minutes", sa.BigInteger(), nullable=True),
        sa.Column("cap_units", sa.BigInteger(), nullable=True),
        sa.Column("cap_tasks", sa.BigInteger(), nullable=True),
        sa.Column(
            "multiplier_bps",
            sa.BigInteger(),
            server_default=sa.text("10000"),
            nullable=False,
        ),
        sa.Column(
            "rounding_mode",
            ops_metering_rounding_mode,
            server_default=sa.text("'none'"),
            nullable=False,
        ),
        sa.Column(
            "rounding_step",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("billable_window_minutes", sa.BigInteger(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_metering_meter_policy__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_definition_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_definition.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_metering_meter_policy__tenant_meter_definition",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_metering_meter_policy__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_metering_meter_policy__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_metering_meter_policy__description_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "cap_minutes IS NULL OR cap_minutes >= 0",
            name="ck_ops_metering_meter_policy__cap_minutes_nonnegative",
        ),
        sa.CheckConstraint(
            "cap_units IS NULL OR cap_units >= 0",
            name="ck_ops_metering_meter_policy__cap_units_nonnegative",
        ),
        sa.CheckConstraint(
            "cap_tasks IS NULL OR cap_tasks >= 0",
            name="ck_ops_metering_meter_policy__cap_tasks_nonnegative",
        ),
        sa.CheckConstraint(
            "multiplier_bps >= 0",
            name="ck_ops_metering_meter_policy__multiplier_bps_nonnegative",
        ),
        sa.CheckConstraint(
            "rounding_step > 0",
            name="ck_ops_metering_meter_policy__rounding_step_positive",
        ),
        sa.CheckConstraint(
            "billable_window_minutes IS NULL OR billable_window_minutes >= 0",
            name="ck_ops_metering_meter_policy__billable_window_nonnegative",
        ),
        sa.CheckConstraint(
            (
                "effective_to IS NULL OR effective_from IS NULL OR"
                " effective_to >= effective_from"
            ),
            name="ck_ops_metering_meter_policy__effective_window_bounds",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_metering_meter_policy"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_meter_policy__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "meter_definition_id",
            "code",
            name="ux_ops_metering_meter_policy__tenant_meter_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_metering_meter_policy__tenant_meter_active",
        "ops_metering_meter_policy",
        ["tenant_id", "meter_definition_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_metering_usage_session",
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
        sa.Column("meter_definition_id", sa.Uuid(), nullable=False),
        sa.Column("meter_policy_id", sa.Uuid(), nullable=True),
        sa.Column("usage_record_id", sa.Uuid(), nullable=True),
        sa.Column("tracked_namespace", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("tracked_id", sa.Uuid(), nullable=True),
        sa.Column("tracked_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            ops_metering_usage_session_status,
            server_default=sa.text("'idle'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "elapsed_seconds",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("idempotency_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("last_actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_metering_usage_session__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_definition_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_definition.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_definition.id",
            ],
            ondelete="RESTRICT",
            name="fkx_ops_metering_usage_session__tenant_meter_definition",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_policy_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_policy.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_policy.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_metering_usage_session__tenant_meter_policy",
        ),
        sa.ForeignKeyConstraint(
            ["last_actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_metering_usage_session__last_actor_uid__admin_user",
        ),
        sa.CheckConstraint(
            "length(btrim(tracked_namespace)) > 0",
            name="ck_ops_metering_usage_session__tracked_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "tracked_ref IS NULL OR length(btrim(tracked_ref)) > 0",
            name="ck_ops_metering_usage_session__tracked_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "tracked_id IS NOT NULL OR tracked_ref IS NOT NULL",
            name="ck_ops_metering_usage_session__tracked_target_required",
        ),
        sa.CheckConstraint(
            "elapsed_seconds >= 0",
            name="ck_ops_metering_usage_session__elapsed_seconds_nonnegative",
        ),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR length(btrim(idempotency_key)) > 0",
            name="ck_ops_metering_usage_session__idempotency_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_metering_usage_session"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_usage_session__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_metering_usage_session__tenant_tracking",
        "ops_metering_usage_session",
        [
            "tenant_id",
            "tracked_namespace",
            "meter_definition_id",
            "tracked_id",
            "tracked_ref",
        ],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_ops_metering_usage_session__tenant_idempotency_key",
        "ops_metering_usage_session",
        ["tenant_id", "idempotency_key"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "ops_metering_usage_record",
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
        sa.Column("meter_definition_id", sa.Uuid(), nullable=False),
        sa.Column("meter_policy_id", sa.Uuid(), nullable=True),
        sa.Column("usage_session_id", sa.Uuid(), nullable=True),
        sa.Column("rated_usage_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "measured_minutes",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "measured_units",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "measured_tasks",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "status",
            ops_metering_usage_record_status,
            server_default=sa.text("'recorded'"),
            nullable=False,
        ),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(length=1024), nullable=True),
        sa.Column("idempotency_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_metering_usage_record__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_definition_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_definition.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_definition.id",
            ],
            ondelete="RESTRICT",
            name="fkx_ops_metering_usage_record__tenant_meter_definition",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_policy_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_policy.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_policy.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_metering_usage_record__tenant_meter_policy",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "usage_session_id"],
            [
                f"{_SCHEMA}.ops_metering_usage_session.tenant_id",
                f"{_SCHEMA}.ops_metering_usage_session.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_metering_usage_record__tenant_usage_session",
        ),
        sa.CheckConstraint(
            "measured_minutes >= 0",
            name="ck_ops_metering_usage_record__measured_minutes_nonnegative",
        ),
        sa.CheckConstraint(
            "measured_units >= 0",
            name="ck_ops_metering_usage_record__measured_units_nonnegative",
        ),
        sa.CheckConstraint(
            "measured_tasks >= 0",
            name="ck_ops_metering_usage_record__measured_tasks_nonnegative",
        ),
        sa.CheckConstraint(
            "(measured_minutes + measured_units + measured_tasks) > 0",
            name="ck_ops_metering_usage_record__measured_positive_required",
        ),
        sa.CheckConstraint(
            "void_reason IS NULL OR length(btrim(void_reason)) > 0",
            name="ck_ops_metering_usage_record__void_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR length(btrim(idempotency_key)) > 0",
            name="ck_ops_metering_usage_record__idempotency_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_ops_metering_usage_record__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_metering_usage_record"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_usage_record__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_metering_usage_record__tenant_meter_occurred",
        "ops_metering_usage_record",
        ["tenant_id", "meter_definition_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_ops_metering_usage_record__tenant_idempotency_key",
        "ops_metering_usage_record",
        ["tenant_id", "idempotency_key"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ux_ops_metering_usage_record__tenant_external_ref",
        "ops_metering_usage_record",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.create_index(
        "ux_ops_metering_usage_record__tenant_usage_session",
        "ops_metering_usage_record",
        ["tenant_id", "usage_session_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("usage_session_id IS NOT NULL"),
    )

    op.create_table(
        "ops_metering_rated_usage",
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
        sa.Column("usage_record_id", sa.Uuid(), nullable=False),
        sa.Column("meter_definition_id", sa.Uuid(), nullable=False),
        sa.Column("meter_policy_id", sa.Uuid(), nullable=True),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=True),
        sa.Column("meter_code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("unit", postgresql.CITEXT(length=32), nullable=False),
        sa.Column(
            "measured_quantity",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "capped_quantity",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "multiplier_bps",
            sa.BigInteger(),
            server_default=sa.text("10000"),
            nullable=False,
        ),
        sa.Column(
            "billable_quantity",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "rated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status",
            ops_metering_rated_usage_status,
            server_default=sa.text("'rated'"),
            nullable=False,
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(length=1024), nullable=True),
        sa.Column("billing_usage_event_id", sa.Uuid(), nullable=True),
        sa.Column("billing_external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_metering_rated_usage__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "usage_record_id"],
            [
                f"{_SCHEMA}.ops_metering_usage_record.tenant_id",
                f"{_SCHEMA}.ops_metering_usage_record.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_metering_rated_usage__tenant_usage_record",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_definition_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_definition.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_definition.id",
            ],
            ondelete="RESTRICT",
            name="fkx_ops_metering_rated_usage__tenant_meter_definition",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "meter_policy_id"],
            [
                f"{_SCHEMA}.ops_metering_meter_policy.tenant_id",
                f"{_SCHEMA}.ops_metering_meter_policy.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_metering_rated_usage__tenant_meter_policy",
        ),
        sa.CheckConstraint(
            "length(btrim(meter_code)) > 0",
            name="ck_ops_metering_rated_usage__meter_code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(unit)) > 0",
            name="ck_ops_metering_rated_usage__unit_nonempty",
        ),
        sa.CheckConstraint(
            "measured_quantity >= 0",
            name="ck_ops_metering_rated_usage__measured_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "capped_quantity >= 0",
            name="ck_ops_metering_rated_usage__capped_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "multiplier_bps >= 0",
            name="ck_ops_metering_rated_usage__multiplier_bps_nonnegative",
        ),
        sa.CheckConstraint(
            "billable_quantity >= 0",
            name="ck_ops_metering_rated_usage__billable_quantity_nonnegative",
        ),
        sa.CheckConstraint(
            "void_reason IS NULL OR length(btrim(void_reason)) > 0",
            name="ck_ops_metering_rated_usage__void_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "billing_external_ref IS NULL OR"
                " length(btrim(billing_external_ref)) > 0"
            ),
            name="ck_ops_metering_rated_usage__billing_ext_ref_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_metering_rated_usage"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_metering_rated_usage__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "usage_record_id",
            name="ux_ops_metering_rated_usage__tenant_usage_record",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_metering_rated_usage__tenant_meter_occurred",
        "ops_metering_rated_usage",
        ["tenant_id", "meter_code", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_ops_metering_rated_usage__tenant_billing_external_ref",
        "ops_metering_rated_usage",
        ["tenant_id", "billing_external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("billing_external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_ops_metering_rated_usage__tenant_billing_external_ref",
        table_name="ops_metering_rated_usage",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_metering_rated_usage__tenant_meter_occurred",
        table_name="ops_metering_rated_usage",
        schema=_SCHEMA,
    )
    op.drop_table("ops_metering_rated_usage", schema=_SCHEMA)

    op.drop_index(
        "ux_ops_metering_usage_record__tenant_usage_session",
        table_name="ops_metering_usage_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_ops_metering_usage_record__tenant_external_ref",
        table_name="ops_metering_usage_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_ops_metering_usage_record__tenant_idempotency_key",
        table_name="ops_metering_usage_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_metering_usage_record__tenant_meter_occurred",
        table_name="ops_metering_usage_record",
        schema=_SCHEMA,
    )
    op.drop_table("ops_metering_usage_record", schema=_SCHEMA)

    op.drop_index(
        "ux_ops_metering_usage_session__tenant_idempotency_key",
        table_name="ops_metering_usage_session",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_metering_usage_session__tenant_tracking",
        table_name="ops_metering_usage_session",
        schema=_SCHEMA,
    )
    op.drop_table("ops_metering_usage_session", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_metering_meter_policy__tenant_meter_active",
        table_name="ops_metering_meter_policy",
        schema=_SCHEMA,
    )
    op.drop_table("ops_metering_meter_policy", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_metering_meter_definition__tenant_active",
        table_name="ops_metering_meter_definition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_metering_meter_definition", schema=_SCHEMA)

    ops_metering_rated_usage_status = postgresql.ENUM(
        name="ops_metering_rated_usage_status",
        schema=_SCHEMA,
    )
    ops_metering_usage_record_status = postgresql.ENUM(
        name="ops_metering_usage_record_status",
        schema=_SCHEMA,
    )
    ops_metering_usage_session_status = postgresql.ENUM(
        name="ops_metering_usage_session_status",
        schema=_SCHEMA,
    )
    ops_metering_rounding_mode = postgresql.ENUM(
        name="ops_metering_rounding_mode",
        schema=_SCHEMA,
    )
    ops_metering_aggregation_mode = postgresql.ENUM(
        name="ops_metering_aggregation_mode",
        schema=_SCHEMA,
    )
    ops_metering_meter_unit = postgresql.ENUM(
        name="ops_metering_meter_unit",
        schema=_SCHEMA,
    )

    bind = op.get_bind()
    ops_metering_rated_usage_status.drop(bind, checkfirst=True)
    ops_metering_usage_record_status.drop(bind, checkfirst=True)
    ops_metering_usage_session_status.drop(bind, checkfirst=True)
    ops_metering_rounding_mode.drop(bind, checkfirst=True)
    ops_metering_aggregation_mode.drop(bind, checkfirst=True)
    ops_metering_meter_unit.drop(bind, checkfirst=True)
