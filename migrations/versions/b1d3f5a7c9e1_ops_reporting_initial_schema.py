"""ops_reporting initial schema

Revision ID: b1d3f5a7c9e1
Revises: e2a5c8d9f0b1
Create Date: 2026-02-14 09:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "b1d3f5a7c9e1"
down_revision: Union[str, None] = "e2a5c8d9f0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_reporting_formula_type = postgresql.ENUM(
        "count_rows",
        "sum_column",
        "avg_column",
        "min_column",
        "max_column",
        name="ops_reporting_formula_type",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_reporting_job_status = postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        name="ops_reporting_job_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_reporting_snapshot_status = postgresql.ENUM(
        "draft",
        "generated",
        "published",
        "archived",
        name="ops_reporting_snapshot_status",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_reporting_formula_type.create(bind, checkfirst=True)
    ops_reporting_job_status.create(bind, checkfirst=True)
    ops_reporting_snapshot_status.create(bind, checkfirst=True)

    op.create_table(
        "ops_reporting_metric_definition",
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
            "formula_type",
            ops_reporting_formula_type,
            server_default=sa.text("'count_rows'"),
            nullable=False,
        ),
        sa.Column("source_table", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("source_time_column", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("source_value_column", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("scope_column", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "source_filter",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
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
            name="fk_ops_reporting_metric_definition__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_reporting_metric_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_reporting_metric_definition__name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_table)) > 0",
            name="ck_ops_reporting_metric_definition__source_table_nonempty",
        ),
        sa.CheckConstraint(
            "source_time_column IS NULL OR length(btrim(source_time_column)) > 0",
            name="ck_ops_reporting_metric_definition__source_time_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "source_value_column IS NULL OR length(btrim(source_value_column)) > 0",
            name="ck_ops_reporting_metric_def__source_value_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "scope_column IS NULL OR length(btrim(scope_column)) > 0",
            name="ck_ops_reporting_metric_def__scope_column_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "formula_type = 'count_rows' OR source_value_column IS NOT NULL",
            name="ck_ops_reporting_metric_definition__value_column_required",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_reporting_metric_definition__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_metric_definition"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_metric_definition__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_reporting_metric_definition__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_metric_definition__tenant_active",
        "ops_reporting_metric_definition",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_reporting_report_definition",
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
        sa.Column(
            "metric_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "group_by_json",
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
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_reporting_report_definition__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_reporting_report_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_reporting_report_definition__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_reporting_report_definition__description_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "metric_codes IS NULL OR jsonb_typeof(metric_codes) = 'array'",
            name="ck_ops_reporting_report_definition__metric_codes_array",
        ),
        sa.CheckConstraint(
            "group_by_json IS NULL OR jsonb_typeof(group_by_json) = 'array'",
            name="ck_ops_reporting_report_definition__group_by_json_array",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_report_definition"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_report_definition__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_reporting_report_definition__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_report_definition__tenant_active",
        "ops_reporting_report_definition",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_reporting_metric_series",
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
        sa.Column("metric_definition_id", sa.Uuid(), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "scope_key",
            postgresql.CITEXT(length=255),
            server_default=sa.text("'__all__'"),
            nullable=False,
        ),
        sa.Column(
            "value_numeric",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "source_count",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("aggregation_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_reporting_metric_series__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "metric_definition_id"],
            [
                f"{_SCHEMA}.ops_reporting_metric_definition.tenant_id",
                f"{_SCHEMA}.ops_reporting_metric_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_metric_series__tenant_metric_definition",
        ),
        sa.CheckConstraint(
            "bucket_end > bucket_start",
            name="ck_ops_reporting_metric_series__bucket_window_bounds",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_metric_series__scope_key_nonempty",
        ),
        sa.CheckConstraint(
            "source_count >= 0",
            name="ck_ops_reporting_metric_series__source_count_nonnegative",
        ),
        sa.CheckConstraint(
            "length(btrim(aggregation_key)) > 0",
            name="ck_ops_reporting_metric_series__aggregation_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_metric_series"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_metric_series__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "aggregation_key",
            name="ux_ops_reporting_metric_series__tenant_aggregation_key",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "metric_definition_id",
            "bucket_start",
            "bucket_end",
            "scope_key",
            name="ux_ops_reporting_metric_series__tenant_bucket_scope",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_metric_series__tenant_metric_bucket",
        "ops_reporting_metric_series",
        ["tenant_id", "metric_definition_id", "bucket_start"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_reporting_aggregation_job",
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
        sa.Column("metric_definition_id", sa.Uuid(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "bucket_minutes",
            sa.BigInteger(),
            server_default=sa.text("60"),
            nullable=False,
        ),
        sa.Column(
            "scope_key",
            postgresql.CITEXT(length=255),
            server_default=sa.text("'__all__'"),
            nullable=False,
        ),
        sa.Column("idempotency_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "status",
            ops_reporting_job_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_reporting_aggregation_job__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "metric_definition_id"],
            [
                f"{_SCHEMA}.ops_reporting_metric_definition.tenant_id",
                f"{_SCHEMA}.ops_reporting_metric_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_aggregation_job__tenant_metric_definition",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_reporting_aggregation_job__created_by_uid__admin_user",
        ),
        sa.CheckConstraint(
            "window_end > window_start",
            name="ck_ops_reporting_aggregation_job__window_bounds",
        ),
        sa.CheckConstraint(
            "bucket_minutes > 0",
            name="ck_ops_reporting_aggregation_job__bucket_minutes_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_aggregation_job__scope_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_ops_reporting_aggregation_job__idempotency_key_nonempty",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR length(btrim(error_message)) > 0",
            name="ck_ops_reporting_aggregation_job__error_message_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_aggregation_job"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_aggregation_job__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="ux_ops_reporting_aggregation_job__tenant_idempotency_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_aggregation_job__tenant_metric_window",
        "ops_reporting_aggregation_job",
        ["tenant_id", "metric_definition_id", "window_start", "window_end"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_reporting_report_snapshot",
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
        sa.Column("report_definition_id", sa.Uuid(), nullable=True),
        sa.Column(
            "metric_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status",
            ops_reporting_snapshot_status,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "scope_key",
            postgresql.CITEXT(length=255),
            server_default=sa.text("'__all__'"),
            nullable=False,
        ),
        sa.Column(
            "summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("archived_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_reporting_report_snapshot__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "report_definition_id"],
            [
                f"{_SCHEMA}.ops_reporting_report_definition.tenant_id",
                f"{_SCHEMA}.ops_reporting_report_definition.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_reporting_report_snapshot__tenant_report_definition",
        ),
        sa.ForeignKeyConstraint(
            ["generated_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_reporting_report_snapshot__generated_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_reporting_report_snapshot__published_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_reporting_report_snapshot__archived_by_uid__admin_user",
        ),
        sa.CheckConstraint(
            "window_start IS NULL OR window_end IS NULL OR window_end > window_start",
            name="ck_ops_reporting_report_snapshot__window_bounds",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_report_snapshot__scope_key_nonempty",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_ops_reporting_report_snapshot__note_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "report_definition_id IS NOT NULL OR metric_codes IS NOT NULL",
            name="ck_ops_reporting_report_snapshot__metric_source_required",
        ),
        sa.CheckConstraint(
            "metric_codes IS NULL OR jsonb_typeof(metric_codes) = 'array'",
            name="ck_ops_reporting_report_snapshot__metric_codes_array",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_report_snapshot"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_report_snapshot__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_report_snapshot__tenant_status_generated",
        "ops_reporting_report_snapshot",
        ["tenant_id", "status", "generated_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_report_snapshot__tenant_window",
        "ops_reporting_report_snapshot",
        ["tenant_id", "window_start", "window_end"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_reporting_kpi_threshold",
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
        sa.Column("metric_definition_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scope_key",
            postgresql.CITEXT(length=255),
            server_default=sa.text("'__all__'"),
            nullable=False,
        ),
        sa.Column("target_value", sa.BigInteger(), nullable=True),
        sa.Column("warn_low", sa.BigInteger(), nullable=True),
        sa.Column("warn_high", sa.BigInteger(), nullable=True),
        sa.Column("critical_low", sa.BigInteger(), nullable=True),
        sa.Column("critical_high", sa.BigInteger(), nullable=True),
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
            name="fk_ops_reporting_kpi_threshold__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "metric_definition_id"],
            [
                f"{_SCHEMA}.ops_reporting_metric_definition.tenant_id",
                f"{_SCHEMA}.ops_reporting_metric_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_kpi_threshold__tenant_metric_definition",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ops_reporting_kpi_threshold__scope_key_nonempty",
        ),
        sa.CheckConstraint(
            "warn_low IS NULL OR warn_high IS NULL OR warn_low <= warn_high",
            name="ck_ops_reporting_kpi_threshold__warn_bounds",
        ),
        sa.CheckConstraint(
            (
                "critical_low IS NULL OR critical_high IS NULL OR"
                " critical_low <= critical_high"
            ),
            name="ck_ops_reporting_kpi_threshold__critical_bounds",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_reporting_kpi_threshold__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_kpi_threshold"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_kpi_threshold__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "metric_definition_id",
            "scope_key",
            name="ux_ops_reporting_kpi_threshold__tenant_metric_scope",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_kpi_threshold__tenant_metric_active",
        "ops_reporting_kpi_threshold",
        ["tenant_id", "metric_definition_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_reporting_kpi_threshold__tenant_metric_active",
        table_name="ops_reporting_kpi_threshold",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_kpi_threshold", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_reporting_report_snapshot__tenant_window",
        table_name="ops_reporting_report_snapshot",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_reporting_report_snapshot__tenant_status_generated",
        table_name="ops_reporting_report_snapshot",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_report_snapshot", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_reporting_aggregation_job__tenant_metric_window",
        table_name="ops_reporting_aggregation_job",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_aggregation_job", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_reporting_metric_series__tenant_metric_bucket",
        table_name="ops_reporting_metric_series",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_metric_series", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_reporting_report_definition__tenant_active",
        table_name="ops_reporting_report_definition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_report_definition", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_reporting_metric_definition__tenant_active",
        table_name="ops_reporting_metric_definition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_metric_definition", schema=_SCHEMA)

    ops_reporting_snapshot_status = postgresql.ENUM(
        name="ops_reporting_snapshot_status",
        schema=_SCHEMA,
    )
    ops_reporting_job_status = postgresql.ENUM(
        name="ops_reporting_job_status",
        schema=_SCHEMA,
    )
    ops_reporting_formula_type = postgresql.ENUM(
        name="ops_reporting_formula_type",
        schema=_SCHEMA,
    )

    bind = op.get_bind()
    ops_reporting_snapshot_status.drop(bind, checkfirst=True)
    ops_reporting_job_status.drop(bind, checkfirst=True)
    ops_reporting_formula_type.drop(bind, checkfirst=True)
