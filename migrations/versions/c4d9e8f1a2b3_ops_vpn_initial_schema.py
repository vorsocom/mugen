"""ops_vpn initial schema

Revision ID: c4d9e8f1a2b3
Revises: 8f0c1d2e3a4b
Create Date: 2026-02-11 21:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "c4d9e8f1a2b3"
down_revision: Union[str, None] = "8f0c1d2e3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_vpn_vendor_status = postgresql.ENUM(
        "candidate",
        "active",
        "suspended",
        "delisted",
        name="ops_vpn_vendor_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_vpn_vendor_verification_type = postgresql.ENUM(
        "onboarding",
        "reverification",
        name="ops_vpn_vendor_verification_type",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_vpn_vendor_verification_status = postgresql.ENUM(
        "pending",
        "passed",
        "failed",
        name="ops_vpn_vendor_verification_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_vpn_vendor_metric_type = postgresql.ENUM(
        "time_to_quote",
        "completion_rate",
        "complaint_rate",
        "response_sla_adherence",
        name="ops_vpn_vendor_metric_type",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_vpn_vendor_status.create(bind, checkfirst=True)
    ops_vpn_vendor_verification_type.create(bind, checkfirst=True)
    ops_vpn_vendor_verification_status.create(bind, checkfirst=True)
    ops_vpn_vendor_metric_type.create(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # taxonomy tables
    # ------------------------------------------------------------------
    op.create_table(
        "ops_vpn_taxonomy_domain",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=16), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_taxonomy_domain__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_taxonomy_domain__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_taxonomy_domain__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_taxonomy_domain__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_taxonomy_domain"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_taxonomy_domain__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_taxonomy_domain__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_domain_tenant_id"),
        "ops_vpn_taxonomy_domain",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_domain_code"),
        "ops_vpn_taxonomy_domain",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_domain_name"),
        "ops_vpn_taxonomy_domain",
        ["name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_taxonomy_domain__tenant_code",
        "ops_vpn_taxonomy_domain",
        ["tenant_id", "code"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_taxonomy_category",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_domain_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=16), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_taxonomy_category__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "taxonomy_domain_id"),
            (f"{_SCHEMA}.ops_vpn_taxonomy_domain.tenant_id", f"{_SCHEMA}.ops_vpn_taxonomy_domain.id"),
            name="fkx_ops_vpn_taxonomy_category__tenant_domain",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_taxonomy_category__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_taxonomy_category__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_taxonomy_category__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_taxonomy_category"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_taxonomy_category__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_taxonomy_category__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_category_tenant_id"),
        "ops_vpn_taxonomy_category",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_category_taxonomy_domain_id"),
        "ops_vpn_taxonomy_category",
        ["taxonomy_domain_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_category_code"),
        "ops_vpn_taxonomy_category",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_category_name"),
        "ops_vpn_taxonomy_category",
        ["name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_taxonomy_category__tenant_domain_code",
        "ops_vpn_taxonomy_category",
        ["tenant_id", "taxonomy_domain_id", "code"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_taxonomy_subcategory",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("taxonomy_category_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=16), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_taxonomy_subcategory__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "taxonomy_category_id"),
            (
                f"{_SCHEMA}.ops_vpn_taxonomy_category.tenant_id",
                f"{_SCHEMA}.ops_vpn_taxonomy_category.id",
            ),
            name="fkx_ops_vpn_taxonomy_subcategory__tenant_category",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_taxonomy_subcategory__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_vpn_taxonomy_subcategory__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_vpn_taxonomy_subcategory__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_taxonomy_subcategory"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_taxonomy_subcategory__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_taxonomy_subcategory__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_subcategory_tenant_id"),
        "ops_vpn_taxonomy_subcategory",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_subcategory_taxonomy_category_id"),
        "ops_vpn_taxonomy_subcategory",
        ["taxonomy_category_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_subcategory_code"),
        "ops_vpn_taxonomy_subcategory",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_taxonomy_subcategory_name"),
        "ops_vpn_taxonomy_subcategory",
        ["name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_taxonomy_subcategory__tenant_category_code",
        "ops_vpn_taxonomy_subcategory",
        ["tenant_id", "taxonomy_category_id", "code"],
        unique=False,
        schema=_SCHEMA,
    )

    # ------------------------------------------------------------------
    # vendor + operations tables
    # ------------------------------------------------------------------
    op.create_table(
        "ops_vpn_vendor",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column(
            "status",
            ops_vpn_vendor_status,
            server_default=sa.text("'candidate'"),
            nullable=False,
        ),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reverification_cadence_days",
            sa.BigInteger(),
            server_default=sa.text("365"),
            nullable=False,
        ),
        sa.Column("last_reverified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reverification_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_vpn_vendor__deleted_by_user_id__admin_user",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_vpn_vendor__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_ops_vpn_vendor__display_name_nonempty",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_ops_vpn_vendor__external_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "reverification_cadence_days > 0",
            name="ck_ops_vpn_vendor__reverification_cadence_days_positive",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_ops_vpn_vendor__not_deleted_and_not_deleted_by",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_vpn_vendor__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_tenant_id"),
        "ops_vpn_vendor",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_code"),
        "ops_vpn_vendor",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_display_name"),
        "ops_vpn_vendor",
        ["display_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_status"),
        "ops_vpn_vendor",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_onboarding_completed_at"),
        "ops_vpn_vendor",
        ["onboarding_completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_last_reverified_at"),
        "ops_vpn_vendor",
        ["last_reverified_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_next_reverification_due_at"),
        "ops_vpn_vendor",
        ["next_reverification_due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_external_ref"),
        "ops_vpn_vendor",
        ["external_ref"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_deleted_at"),
        "ops_vpn_vendor",
        ["deleted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor__tenant_status",
        "ops_vpn_vendor",
        ["tenant_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor__tenant_reverification_due",
        "ops_vpn_vendor",
        ["tenant_id", "next_reverification_due_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_category",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("category_code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=256), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_category__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{_SCHEMA}.ops_vpn_vendor.tenant_id", f"{_SCHEMA}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_category__tenant_vendor",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(category_code)) > 0",
            name="ck_ops_vpn_vendor_category__category_code_nonempty",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_ops_vpn_vendor_category__display_name_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_category"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_category__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "category_code",
            name="ux_ops_vpn_vendor_category__tenant_vendor_category_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_category_tenant_id"),
        "ops_vpn_vendor_category",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_category_vendor_id"),
        "ops_vpn_vendor_category",
        ["vendor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_category_category_code"),
        "ops_vpn_vendor_category",
        ["category_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_category_display_name"),
        "ops_vpn_vendor_category",
        ["display_name"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_category__tenant_category",
        "ops_vpn_vendor_category",
        ["tenant_id", "category_code"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_capability",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("capability_code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("service_region", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_capability__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{_SCHEMA}.ops_vpn_vendor.tenant_id", f"{_SCHEMA}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_capability__tenant_vendor",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(capability_code)) > 0",
            name="ck_ops_vpn_vendor_capability__capability_code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(service_region)) > 0",
            name="ck_ops_vpn_vendor_capability__service_region_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_capability"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_capability__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "capability_code",
            "service_region",
            name="ux_ops_vpn_vendor_capability__tenant_vendor_capability_region",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_capability_tenant_id"),
        "ops_vpn_vendor_capability",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_capability_vendor_id"),
        "ops_vpn_vendor_capability",
        ["vendor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_capability_capability_code"),
        "ops_vpn_vendor_capability",
        ["capability_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_capability_service_region"),
        "ops_vpn_vendor_capability",
        ["service_region"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_capability__tenant_capability_region",
        "ops_vpn_vendor_capability",
        ["tenant_id", "capability_code", "service_region"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_verification",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("verification_type", ops_vpn_vendor_verification_type, nullable=False),
        sa.Column(
            "status",
            ops_vpn_vendor_verification_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.String(length=2048), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_verification__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["checked_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_vpn_vendor_verification__checked_by_user_id__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{_SCHEMA}.ops_vpn_vendor.tenant_id", f"{_SCHEMA}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_verification__tenant_vendor",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name="ck_ops_vpn_vendor_verification__notes_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_verification"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_verification__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_tenant_id"),
        "ops_vpn_vendor_verification",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_vendor_id"),
        "ops_vpn_vendor_verification",
        ["vendor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_verification_type"),
        "ops_vpn_vendor_verification",
        ["verification_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_status"),
        "ops_vpn_vendor_verification",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_checked_at"),
        "ops_vpn_vendor_verification",
        ["checked_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_due_at"),
        "ops_vpn_vendor_verification",
        ["due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_verification_checked_by_user_id"),
        "ops_vpn_vendor_verification",
        ["checked_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_verification__tenant_vendor_checked",
        "ops_vpn_vendor_verification",
        ["tenant_id", "vendor_id", "checked_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_performance_event",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("metric_type", ops_vpn_vendor_metric_type, nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metric_value", sa.BigInteger(), nullable=True),
        sa.Column("metric_numerator", sa.BigInteger(), nullable=True),
        sa.Column("metric_denominator", sa.BigInteger(), nullable=True),
        sa.Column("normalized_score", sa.BigInteger(), nullable=True),
        sa.Column("sample_size", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_performance_event__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{_SCHEMA}.ops_vpn_vendor.tenant_id", f"{_SCHEMA}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_performance_event__tenant_vendor",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "metric_value IS NULL OR metric_value >= 0",
            name="ck_ops_vpn_vendor_performance_event__metric_value_nonneg",
        ),
        sa.CheckConstraint(
            "metric_numerator IS NULL OR metric_numerator >= 0",
            name="ck_ops_vpn_vendor_performance_event__metric_numerator_nonneg",
        ),
        sa.CheckConstraint(
            "metric_denominator IS NULL OR metric_denominator > 0",
            name="ck_ops_vpn_vendor_perf_evt__metric_denominator_positive",
        ),
        sa.CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 100)",
            name="ck_ops_vpn_vendor_performance_event__normalized_score_range",
        ),
        sa.CheckConstraint(
            "sample_size > 0",
            name="ck_ops_vpn_vendor_performance_event__sample_size_positive",
        ),
        sa.CheckConstraint(
            "metric_value IS NOT NULL OR normalized_score IS NOT NULL OR (metric_numerator IS NOT NULL AND metric_denominator IS NOT NULL)",
            name="ck_ops_vpn_vendor_performance_event__value_or_score_present",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_performance_event"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_performance_event__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_performance_event_tenant_id"),
        "ops_vpn_vendor_performance_event",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_performance_event_vendor_id"),
        "ops_vpn_vendor_performance_event",
        ["vendor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_performance_event_metric_type"),
        "ops_vpn_vendor_performance_event",
        ["metric_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_performance_event_observed_at"),
        "ops_vpn_vendor_performance_event",
        ["observed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_performance_event_unit"),
        "ops_vpn_vendor_performance_event",
        ["unit"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_perf_evt__tenant_vendor_metric_observed",
        "ops_vpn_vendor_performance_event",
        ["tenant_id", "vendor_id", "metric_type", "observed_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_vpn_vendor_scorecard",
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
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("time_to_quote_score", sa.BigInteger(), nullable=True),
        sa.Column("completion_rate_score", sa.BigInteger(), nullable=True),
        sa.Column("complaint_rate_score", sa.BigInteger(), nullable=True),
        sa.Column("response_sla_score", sa.BigInteger(), nullable=True),
        sa.Column("overall_score", sa.BigInteger(), nullable=True),
        sa.Column("event_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_routable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_vpn_vendor_scorecard__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "vendor_id"),
            (f"{_SCHEMA}.ops_vpn_vendor.tenant_id", f"{_SCHEMA}.ops_vpn_vendor.id"),
            name="fkx_ops_vpn_vendor_scorecard__tenant_vendor",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "period_end >= period_start",
            name="ck_ops_vpn_vendor_scorecard__period_end_gte_start",
        ),
        sa.CheckConstraint(
            "event_count >= 0",
            name="ck_ops_vpn_vendor_scorecard__event_count_nonneg",
        ),
        sa.CheckConstraint(
            "time_to_quote_score IS NULL OR (time_to_quote_score >= 0 AND time_to_quote_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__time_to_quote_score_range",
        ),
        sa.CheckConstraint(
            "completion_rate_score IS NULL OR (completion_rate_score >= 0 AND completion_rate_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__completion_rate_score_range",
        ),
        sa.CheckConstraint(
            "complaint_rate_score IS NULL OR (complaint_rate_score >= 0 AND complaint_rate_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__complaint_rate_score_range",
        ),
        sa.CheckConstraint(
            "response_sla_score IS NULL OR (response_sla_score >= 0 AND response_sla_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__response_sla_score_range",
        ),
        sa.CheckConstraint(
            "overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)",
            name="ck_ops_vpn_vendor_scorecard__overall_score_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_vpn_vendor_scorecard"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_vpn_vendor_scorecard__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "vendor_id",
            "period_start",
            "period_end",
            name="ux_ops_vpn_vendor_scorecard__tenant_vendor_period",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_tenant_id"),
        "ops_vpn_vendor_scorecard",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_vendor_id"),
        "ops_vpn_vendor_scorecard",
        ["vendor_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_period_start"),
        "ops_vpn_vendor_scorecard",
        ["period_start"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_period_end"),
        "ops_vpn_vendor_scorecard",
        ["period_end"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_overall_score"),
        "ops_vpn_vendor_scorecard",
        ["overall_score"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_is_routable"),
        "ops_vpn_vendor_scorecard",
        ["is_routable"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_vpn_vendor_scorecard_computed_at"),
        "ops_vpn_vendor_scorecard",
        ["computed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_vpn_vendor_scorecard__tenant_vendor_period_end",
        "ops_vpn_vendor_scorecard",
        ["tenant_id", "vendor_id", "period_end"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("ops_vpn_vendor_scorecard", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor_performance_event", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor_verification", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor_capability", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor_category", schema=_SCHEMA)
    op.drop_table("ops_vpn_vendor", schema=_SCHEMA)
    op.drop_table("ops_vpn_taxonomy_subcategory", schema=_SCHEMA)
    op.drop_table("ops_vpn_taxonomy_category", schema=_SCHEMA)
    op.drop_table("ops_vpn_taxonomy_domain", schema=_SCHEMA)

    bind = op.get_bind()
    for enum_name in (
        "ops_vpn_vendor_metric_type",
        "ops_vpn_vendor_verification_status",
        "ops_vpn_vendor_verification_type",
        "ops_vpn_vendor_status",
    ):
        postgresql.ENUM(name=enum_name, schema=_SCHEMA).drop(bind, checkfirst=True)
