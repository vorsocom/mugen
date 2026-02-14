"""ops_vpn onboarding and scorecard policy primitives

Revision ID: e1b2c3d4f5a6
Revises: c4d9e8f1a2b3
Create Date: 2026-02-12 08:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e1b2c3d4f5a6"
down_revision: Union[str, None] = "c4d9e8f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    op.create_table(
        "ops_vpn_verification_criterion",
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
        sa.Column("name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("verification_type", postgresql.CITEXT(length=32), nullable=True),
        sa.Column(
            "is_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "sort_order",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_verification_criterion__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_verification_criterion__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_verification_criterion__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_verification_criterion__description_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "verification_type IS NULL OR length(btrim(verification_type)) > 0",
            name="ck_ops_vpn_verif_criterion__verification_type_nonempty",
        ),
        sa.CheckConstraint(
            "sort_order >= 0",
            name="ck_ops_vpn_verification_criterion__sort_order_nonneg",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_verification_criterion"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_verification_criterion__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_verification_criterion__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_verification_criterion_tenant_id"),
        "ops_vpn_verification_criterion",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_verification_criterion_code"),
        "ops_vpn_verification_criterion",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_verification_criterion_name"),
        "ops_vpn_verification_criterion",
        ["name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_verification_criterion_verification_type"),
        "ops_vpn_verification_criterion",
        ["verification_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_verification_criterion__tenant_verification_type",
        "ops_vpn_verification_criterion",
        ["tenant_id", "verification_type"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_verification_check",
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
        sa.Column("vendor_verification_id", sa.Uuid(), nullable=False),
        sa.Column("criterion_id", sa.Uuid(), nullable=True),
        sa.Column("criterion_code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "is_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=2048), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_verification_check__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["checked_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_vpn_vendor_verif_check__checked_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_verification_id"),
            (
                "mugen.ops_vpn_vendor_verification.tenant_id",
                "mugen.ops_vpn_vendor_verification.id",
            ),
            name="fkx_ops_vpn_vendor_verification_check__tenant_verification",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "criterion_id"),
            (
                "mugen.ops_vpn_verification_criterion.tenant_id",
                "mugen.ops_vpn_verification_criterion.id",
            ),
            name="fkx_ops_vpn_vendor_verification_check__tenant_criterion",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "length(btrim(criterion_code)) > 0",
            name="ck_ops_vpn_vendor_verification_check__criterion_code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_ops_vpn_vendor_verification_check__status_nonempty",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name="ck_ops_vpn_vendor_verification_check__notes_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_verification_check"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_verification_check__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "vendor_verification_id",
            "criterion_code",
            name="ux_ops_vpn_vendor_verif_check__tenant_verif_criterion",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_tenant_id"),
        "ops_vpn_vendor_verification_check",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verif_check_vendor_verification_id",
        "ops_vpn_vendor_verification_check",
        ["vendor_verification_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_criterion_id"),
        "ops_vpn_vendor_verification_check",
        ["criterion_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_criterion_code"),
        "ops_vpn_vendor_verification_check",
        ["criterion_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_status"),
        "ops_vpn_vendor_verification_check",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_checked_at"),
        "ops_vpn_vendor_verification_check",
        ["checked_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_due_at"),
        "ops_vpn_vendor_verification_check",
        ["due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_check_checked_by_user_id"),
        "ops_vpn_vendor_verification_check",
        ["checked_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verif_check__tenant_verif_status",
        "ops_vpn_vendor_verification_check",
        ["tenant_id", "vendor_verification_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_verification_artifact",
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
        sa.Column("vendor_verification_id", sa.Uuid(), nullable=False),
        sa.Column("verification_check_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("uri", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column("content_hash", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notes", sa.String(length=2048), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_verif_artifact__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_vpn_vendor_verif_artifact__uploaded_by_uid__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_verification_id"),
            (
                "mugen.ops_vpn_vendor_verification.tenant_id",
                "mugen.ops_vpn_vendor_verification.id",
            ),
            name="fkx_ops_vpn_vendor_verification_artifact__tenant_verification",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "verification_check_id"),
            (
                "mugen.ops_vpn_vendor_verification_check.tenant_id",
                "mugen.ops_vpn_vendor_verification_check.id",
            ),
            name="fkx_ops_vpn_vendor_verification_artifact__tenant_check",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "length(btrim(artifact_type)) > 0",
            name="ck_ops_vpn_vendor_verification_artifact__artifact_type_nonempty",
        ),
        sa.CheckConstraint(
            "uri IS NULL OR length(btrim(uri)) > 0",
            name="ck_ops_vpn_vendor_verification_artifact__uri_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "content_hash IS NULL OR length(btrim(content_hash)) > 0",
            name="ck_ops_vpn_vendor_verif_artifact__content_hash_nonempty",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name="ck_ops_vpn_vendor_verification_artifact__notes_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_verification_artifact"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_verification_artifact__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_artifact_tenant_id"),
        "ops_vpn_vendor_verification_artifact",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verif_artifact_vendor_verification_id",
        "ops_vpn_vendor_verification_artifact",
        ["vendor_verification_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verif_artifact_verification_check_id",
        "ops_vpn_vendor_verification_artifact",
        ["verification_check_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_artifact_artifact_type"),
        "ops_vpn_vendor_verification_artifact",
        ["artifact_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verif_artifact_uploaded_by_user_id",
        "ops_vpn_vendor_verification_artifact",
        ["uploaded_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_artifact_uploaded_at"),
        "ops_vpn_vendor_verification_artifact",
        ["uploaded_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verif_artifact__tenant_verif_uploaded",
        "ops_vpn_vendor_verification_artifact",
        ["tenant_id", "vendor_verification_id", "uploaded_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_scorecard_policy",
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
        sa.Column(
            "code",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("display_name", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "time_to_quote_weight",
            sa.BigInteger(),
            server_default=sa.text("25"),
            nullable=False,
        ),
        sa.Column(
            "completion_rate_weight",
            sa.BigInteger(),
            server_default=sa.text("25"),
            nullable=False,
        ),
        sa.Column(
            "complaint_rate_weight",
            sa.BigInteger(),
            server_default=sa.text("25"),
            nullable=False,
        ),
        sa.Column(
            "response_sla_weight",
            sa.BigInteger(),
            server_default=sa.text("25"),
            nullable=False,
        ),
        sa.Column(
            "min_sample_size",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "minimum_overall_score",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "require_all_metrics",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_scorecard_policy__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_scorecard_policy__code_nonempty",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_ops_vpn_scorecard_policy__display_name_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "time_to_quote_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__time_to_quote_weight_nonneg",
        ),
        sa.CheckConstraint(
            "completion_rate_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__completion_rate_weight_nonneg",
        ),
        sa.CheckConstraint(
            "complaint_rate_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__complaint_rate_weight_nonneg",
        ),
        sa.CheckConstraint(
            "response_sla_weight >= 0",
            name="ck_ops_vpn_scorecard_policy__response_sla_weight_nonneg",
        ),
        sa.CheckConstraint(
            (
                "time_to_quote_weight + completion_rate_weight + "
                "complaint_rate_weight + response_sla_weight > 0"
            ),
            name="ck_ops_vpn_scorecard_policy__weight_sum_positive",
        ),
        sa.CheckConstraint(
            "min_sample_size > 0",
            name="ck_ops_vpn_scorecard_policy__min_sample_size_positive",
        ),
        sa.CheckConstraint(
            "minimum_overall_score >= 0 AND minimum_overall_score <= 100",
            name="ck_ops_vpn_scorecard_policy__minimum_overall_score_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_scorecard_policy"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_scorecard_policy__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_scorecard_policy__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_scorecard_policy_tenant_id"),
        "ops_vpn_scorecard_policy",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_scorecard_policy_code"),
        "ops_vpn_scorecard_policy",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_scorecard_policy__tenant_code",
        "ops_vpn_scorecard_policy",
        ["tenant_id", "code"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("ops_vpn_scorecard_policy", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor_verification_artifact", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor_verification_check", schema=_SCHEMA)
    op.drop_table("ops_vpn_verification_criterion", schema=_SCHEMA)
