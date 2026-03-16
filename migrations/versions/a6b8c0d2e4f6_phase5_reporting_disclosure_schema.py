"""phase5 reporting + disclosure schema for snapshot provenance and exports

Revision ID: a6b8c0d2e4f6
Revises: f6d9c2b4a1e7
Create Date: 2026-02-26 16:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "a6b8c0d2e4f6"
down_revision: Union[str, None] = "f6d9c2b4a1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.add_column(
        "ops_reporting_report_snapshot",
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_reporting_report_snapshot",
        sa.Column(
            "provenance_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_reporting_report_snapshot",
        sa.Column("manifest_hash", postgresql.CITEXT(length=64), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_reporting_report_snapshot",
        sa.Column(
            "signature_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema=_SCHEMA,
    )

    op.create_check_constraint(
        "ck_ops_reporting_report_snapshot__trace_id_nonempty_if_set",
        "ops_reporting_report_snapshot",
        "trace_id IS NULL OR length(btrim(trace_id)) > 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_reporting_report_snapshot__manifest_hash_nonempty_if_set",
        "ops_reporting_report_snapshot",
        "manifest_hash IS NULL OR length(btrim(manifest_hash)) > 0",
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_report_snapshot_trace_id"),
        "ops_reporting_report_snapshot",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_report_snapshot_manifest_hash"),
        "ops_reporting_report_snapshot",
        ["manifest_hash"],
        unique=False,
        schema=_SCHEMA,
    )

    export_job_status = postgresql.ENUM(
        "queued",
        "running",
        "completed",
        "failed",
        name="ops_reporting_export_job_status",
        schema=_SCHEMA,
        create_type=False,
    )
    export_job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ops_reporting_export_job",
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
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("export_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "spec_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            export_job_status,
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "manifest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("manifest_hash", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "signature_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("export_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "policy_decision_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_reporting_export_job__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_reporting_export_job__created_by_user_id__admin_user",
        ),
        sa.CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_ops_reporting_export_job__trace_id_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "length(btrim(export_type)) > 0",
            name="ck_ops_reporting_export_job__export_type_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(spec_json) = 'object'",
            name="ck_ops_reporting_export_job__spec_json_object",
        ),
        sa.CheckConstraint(
            "manifest_hash IS NULL OR length(btrim(manifest_hash)) > 0",
            name="ck_ops_reporting_export_job__manifest_hash_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "export_ref IS NULL OR length(btrim(export_ref)) > 0",
            name="ck_ops_reporting_export_job__export_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "error_message IS NULL OR length(btrim(error_message)) > 0",
            name="ck_ops_reporting_export_job__error_message_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_export_job"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_export_job__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_tenant_id"),
        "ops_reporting_export_job",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_trace_id"),
        "ops_reporting_export_job",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_export_type"),
        "ops_reporting_export_job",
        ["export_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_status"),
        "ops_reporting_export_job",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_manifest_hash"),
        "ops_reporting_export_job",
        ["manifest_hash"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_created_by_user_id"),
        "ops_reporting_export_job",
        ["created_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_job_completed_at"),
        "ops_reporting_export_job",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_export_job__tenant_status_created",
        "ops_reporting_export_job",
        ["tenant_id", "status", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_export_job__tenant_trace",
        "ops_reporting_export_job",
        ["tenant_id", "trace_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_reporting_export_item",
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
        sa.Column("export_job_id", sa.Uuid(), nullable=False),
        sa.Column("item_index", sa.BigInteger(), nullable=False),
        sa.Column("resource_type", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "content_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_reporting_export_item__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "export_job_id"],
            [
                f"{_SCHEMA}.ops_reporting_export_job.tenant_id",
                f"{_SCHEMA}.ops_reporting_export_job.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_reporting_export_item__tenant_export_job",
        ),
        sa.CheckConstraint(
            "item_index >= 0",
            name="ck_ops_reporting_export_item__item_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_reporting_export_item__resource_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_ops_reporting_export_item__content_hash_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content_json) = 'object'",
            name="ck_ops_reporting_export_item__content_json_object",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_reporting_export_item"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_reporting_export_item__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "export_job_id",
            "item_index",
            name="ux_ops_reporting_export_item__tenant_job_item_index",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_item_tenant_id"),
        "ops_reporting_export_item",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_item_export_job_id"),
        "ops_reporting_export_item",
        ["export_job_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_item_resource_type"),
        "ops_reporting_export_item",
        ["resource_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_item_resource_id"),
        "ops_reporting_export_item",
        ["resource_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_reporting_export_item_content_hash"),
        "ops_reporting_export_item",
        ["content_hash"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_reporting_export_item__tenant_job_item",
        "ops_reporting_export_item",
        ["tenant_id", "export_job_id", "item_index"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_reporting_export_item__tenant_job_item",
        table_name="ops_reporting_export_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_item_content_hash"),
        table_name="ops_reporting_export_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_item_resource_id"),
        table_name="ops_reporting_export_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_item_resource_type"),
        table_name="ops_reporting_export_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_item_export_job_id"),
        table_name="ops_reporting_export_item",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_item_tenant_id"),
        table_name="ops_reporting_export_item",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_export_item", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_reporting_export_job__tenant_trace",
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_reporting_export_job__tenant_status_created",
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_completed_at"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_created_by_user_id"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_manifest_hash"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_status"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_export_type"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_trace_id"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_export_job_tenant_id"),
        table_name="ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_table("ops_reporting_export_job", schema=_SCHEMA)

    export_job_status = postgresql.ENUM(
        name="ops_reporting_export_job_status",
        schema=_SCHEMA,
    )
    export_job_status.drop(op.get_bind(), checkfirst=True)

    op.drop_index(
        op.f("ix_mugen_ops_reporting_report_snapshot_manifest_hash"),
        table_name="ops_reporting_report_snapshot",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_reporting_report_snapshot_trace_id"),
        table_name="ops_reporting_report_snapshot",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_ops_reporting_report_snapshot__manifest_hash_nonempty_if_set",
        "ops_reporting_report_snapshot",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_ops_reporting_report_snapshot__trace_id_nonempty_if_set",
        "ops_reporting_report_snapshot",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column("ops_reporting_report_snapshot", "signature_json", schema=_SCHEMA)
    op.drop_column("ops_reporting_report_snapshot", "manifest_hash", schema=_SCHEMA)
    op.drop_column("ops_reporting_report_snapshot", "provenance_json", schema=_SCHEMA)
    op.drop_column("ops_reporting_report_snapshot", "trace_id", schema=_SCHEMA)
