"""billing initial schema

Revision ID: bf491cdca026
Revises: 41dc50b08af1
Create Date: 2026-01-14 16:13:11.150344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "bf491cdca026"
down_revision: Union[str, None] = "41dc50b08af1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    # Ensure the application schema exists.
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    # ------------------------------
    # billing_account
    # ------------------------------
    op.create_table(
        "billing_account",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("email", postgresql.CITEXT(length=254), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),

        sa.CheckConstraint("length(btrim(code)) > 0", name="ck_billing_account__code_nonempty"),
        sa.CheckConstraint("length(btrim(display_name)) > 0", name="ck_billing_account__display_name_nonempty"),
        sa.CheckConstraint("email IS NULL OR length(btrim(email)) > 0", name="ck_billing_account__email_nonempty_if_set"),
        sa.CheckConstraint("external_ref IS NULL OR length(btrim(external_ref)) > 0", name="ck_billing_account__external_ref_nonempty_if_set"),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_account__not_deleted_and_not_deleted_by",
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_account__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_billing_account__deleted_by_user_id__admin_user",
        ),

        sa.PrimaryKeyConstraint("id", name="pk_billing_account"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_account__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_account_tenant_id"), "billing_account", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_account_code"), "billing_account", ["code"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_account_display_name"), "billing_account", ["display_name"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_account_email"), "billing_account", ["email"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_account_external_ref"), "billing_account", ["external_ref"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_account_deleted_at"), "billing_account", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_account__tenant_code", "billing_account", ["tenant_id", "code"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_account__tenant_external_ref", "billing_account", ["tenant_id", "external_ref"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_product
    # ------------------------------
    op.create_table(
        "billing_product",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),

        sa.CheckConstraint("length(btrim(code)) > 0", name="ck_billing_product__code_nonempty"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_billing_product__name_nonempty"),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_product__not_deleted_and_not_deleted_by",
        ),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_product__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_billing_product__deleted_by_user_id__admin_user",
        ),

        sa.PrimaryKeyConstraint("id", name="pk_billing_product"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_product__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_product_tenant_id"), "billing_product", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_product_code"), "billing_product", ["code"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_product_name"), "billing_product", ["name"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_product_deleted_at"), "billing_product", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_product__tenant_code", "billing_product", ["tenant_id", "code"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # Enum types
    # ------------------------------
    billing_price_type = postgresql.ENUM(
        "one_time", "recurring", "metered", name="billing_price_type", schema=_SCHEMA, create_type=False
    )
    billing_interval_unit = postgresql.ENUM(
        "day", "week", "month", "year", name="billing_interval_unit", schema=_SCHEMA, create_type=False
    )
    billing_subscription_status = postgresql.ENUM(
        "active", "trialing", "paused", "canceled", "ended",
        name="billing_subscription_status",
        schema=_SCHEMA,
        create_type=False,
    )
    billing_usage_event_status = postgresql.ENUM(
        "recorded", "void", name="billing_usage_event_status", schema=_SCHEMA, create_type=False
    )
    billing_invoice_status = postgresql.ENUM(
        "draft", "issued", "paid", "void", "uncollectible",
        name="billing_invoice_status",
        schema=_SCHEMA,
        create_type=False,
    )
    billing_payment_status = postgresql.ENUM(
        "pending", "succeeded", "failed", "canceled", "refunded",
        name="billing_payment_status",
        schema=_SCHEMA,
        create_type=False,
    )
    billing_ledger_direction = postgresql.ENUM(
        "debit", "credit", name="billing_ledger_direction", schema=_SCHEMA, create_type=False
    )

    billing_price_type.create(op.get_bind(), checkfirst=True)
    billing_interval_unit.create(op.get_bind(), checkfirst=True)
    billing_subscription_status.create(op.get_bind(), checkfirst=True)
    billing_usage_event_status.create(op.get_bind(), checkfirst=True)
    billing_invoice_status.create(op.get_bind(), checkfirst=True)
    billing_payment_status.create(op.get_bind(), checkfirst=True)
    billing_ledger_direction.create(op.get_bind(), checkfirst=True)

    # ------------------------------
    # billing_price
    # ------------------------------
    op.create_table(
        "billing_price",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("product_id", sa.Uuid(), nullable=False),

        sa.Column("code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("price_type", billing_price_type, server_default=sa.text("'one_time'"), nullable=False),
        sa.Column("currency", postgresql.CITEXT(length=3), nullable=False),
        sa.Column("unit_amount", sa.BigInteger(), nullable=True),

        sa.Column("interval_unit", billing_interval_unit, nullable=True),
        sa.Column("interval_count", sa.Integer(), nullable=True),
        sa.Column("trial_period_days", sa.Integer(), nullable=True),
        sa.Column("usage_unit", postgresql.CITEXT(length=64), nullable=True),

        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_price__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_billing_price__deleted_by_user_id__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "product_id"],
            [f"{_SCHEMA}.billing_product.tenant_id", f"{_SCHEMA}.billing_product.id"],
            ondelete="RESTRICT",
            name="fkx_billing_price__tenant_product",
        ),

        sa.CheckConstraint("length(btrim(code)) > 0", name="ck_billing_price__code_nonempty"),
        sa.CheckConstraint("length(btrim(currency)) = 3", name="ck_billing_price__currency_len3"),
        sa.CheckConstraint("unit_amount IS NULL OR unit_amount >= 0", name="ck_billing_price__unit_amount_nonneg_if_set"),
        sa.CheckConstraint("interval_count IS NULL OR interval_count > 0", name="ck_billing_price__interval_count_positive_if_set"),
        sa.CheckConstraint("trial_period_days IS NULL OR trial_period_days >= 0", name="ck_billing_price__trial_period_nonneg_if_set"),
        sa.CheckConstraint("usage_unit IS NULL OR length(btrim(usage_unit)) > 0", name="ck_billing_price__usage_unit_nonempty_if_set"),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_price__not_deleted_and_not_deleted_by",
        ),

        sa.PrimaryKeyConstraint("id", name="pk_billing_price"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_price__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_price_tenant_id"), "billing_price", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_price_product_id"), "billing_price", ["product_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_price_code"), "billing_price", ["code"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_price_price_type"), "billing_price", ["price_type"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_price_currency"), "billing_price", ["currency"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_price_interval_unit"), "billing_price", ["interval_unit"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_price_deleted_at"), "billing_price", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_price__tenant_code", "billing_price", ["tenant_id", "code"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_price__tenant_product", "billing_price", ["tenant_id", "product_id"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_subscription
    # ------------------------------
    op.create_table(
        "billing_subscription",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("price_id", sa.Uuid(), nullable=False),

        sa.Column("status", billing_subscription_status, server_default=sa.text("'active'"), nullable=False),

        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),

        sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_subscription__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_billing_subscription__deleted_by_user_id__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [f"{_SCHEMA}.billing_account.tenant_id", f"{_SCHEMA}.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_subscription__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "price_id"],
            [f"{_SCHEMA}.billing_price.tenant_id", f"{_SCHEMA}.billing_price.id"],
            ondelete="RESTRICT",
            name="fkx_billing_subscription__tenant_price",
        ),

        sa.CheckConstraint("external_ref IS NULL OR length(btrim(external_ref)) > 0", name="ck_billing_subscription__external_ref_nonempty_if_set"),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_subscription__not_deleted_and_not_deleted_by",
        ),

        sa.PrimaryKeyConstraint("id", name="pk_billing_subscription"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_subscription__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_subscription_tenant_id"), "billing_subscription", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_subscription_account_id"), "billing_subscription", ["account_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_subscription_price_id"), "billing_subscription", ["price_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_subscription_status"), "billing_subscription", ["status"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_subscription_started_at"), "billing_subscription", ["started_at"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_subscription_external_ref"), "billing_subscription", ["external_ref"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_subscription_deleted_at"), "billing_subscription", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_subscription__tenant_account", "billing_subscription", ["tenant_id", "account_id"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_subscription__tenant_price", "billing_subscription", ["tenant_id", "price_id"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_invoice
    # ------------------------------
    op.create_table(
        "billing_invoice",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),

        sa.Column("status", billing_invoice_status, server_default=sa.text("'draft'"), nullable=False),
        sa.Column("number", postgresql.CITEXT(length=64), nullable=True),

        sa.Column("currency", postgresql.CITEXT(length=3), nullable=False),

        sa.Column("subtotal_amount", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("tax_amount", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_amount", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("amount_due", sa.BigInteger(), server_default=sa.text("0"), nullable=False),

        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_invoice__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_billing_invoice__deleted_by_user_id__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [f"{_SCHEMA}.billing_account.tenant_id", f"{_SCHEMA}.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_invoice__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            [f"{_SCHEMA}.billing_subscription.tenant_id", f"{_SCHEMA}.billing_subscription.id"],
            ondelete="SET NULL",
            name="fkx_billing_invoice__tenant_subscription",
        ),

        sa.CheckConstraint("length(btrim(currency)) = 3", name="ck_billing_invoice__currency_len3"),
        sa.CheckConstraint("number IS NULL OR length(btrim(number)) > 0", name="ck_billing_invoice__number_nonempty_if_set"),
        sa.CheckConstraint("subtotal_amount >= 0", name="ck_billing_invoice__subtotal_nonneg"),
        sa.CheckConstraint("tax_amount >= 0", name="ck_billing_invoice__tax_nonneg"),
        sa.CheckConstraint("total_amount >= 0", name="ck_billing_invoice__total_nonneg"),
        sa.CheckConstraint("amount_due >= 0", name="ck_billing_invoice__amount_due_nonneg"),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_invoice__not_deleted_and_not_deleted_by",
        ),

        sa.PrimaryKeyConstraint("id", name="pk_billing_invoice"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_invoice__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_invoice_tenant_id"), "billing_invoice", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_account_id"), "billing_invoice", ["account_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_subscription_id"), "billing_invoice", ["subscription_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_status"), "billing_invoice", ["status"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_number"), "billing_invoice", ["number"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_currency"), "billing_invoice", ["currency"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_deleted_at"), "billing_invoice", ["deleted_at"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_invoice__tenant_account", "billing_invoice", ["tenant_id", "account_id"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_invoice_line
    # ------------------------------
    op.create_table(
        "billing_invoice_line",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("price_id", sa.Uuid(), nullable=True),

        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("unit_amount", sa.BigInteger(), nullable=True),
        sa.Column("amount", sa.BigInteger(), server_default=sa.text("0"), nullable=False),

        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),

        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_invoice_line__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            [f"{_SCHEMA}.billing_invoice.tenant_id", f"{_SCHEMA}.billing_invoice.id"],
            ondelete="CASCADE",
            name="fkx_billing_invoice_line__tenant_invoice",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "price_id"],
            [f"{_SCHEMA}.billing_price.tenant_id", f"{_SCHEMA}.billing_price.id"],
            ondelete="SET NULL",
            name="fkx_billing_invoice_line__tenant_price",
        ),

        sa.CheckConstraint("quantity >= 0", name="ck_billing_invoice_line__quantity_nonneg"),
        sa.CheckConstraint("amount >= 0", name="ck_billing_invoice_line__amount_nonneg"),

        sa.PrimaryKeyConstraint("id", name="pk_billing_invoice_line"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_invoice_line__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_invoice_line_tenant_id"), "billing_invoice_line", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_line_invoice_id"), "billing_invoice_line", ["invoice_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_invoice_line_price_id"), "billing_invoice_line", ["price_id"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_invoice_line__tenant_invoice", "billing_invoice_line", ["tenant_id", "invoice_id"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_payment
    # ------------------------------
    op.create_table(
        "billing_payment",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),

        sa.Column("status", billing_payment_status, server_default=sa.text("'pending'"), nullable=False),

        sa.Column("currency", postgresql.CITEXT(length=3), nullable=False),
        sa.Column("amount", sa.BigInteger(), server_default=sa.text("0"), nullable=False),

        sa.Column("provider", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),

        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),

        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_payment__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [f"{_SCHEMA}.billing_account.tenant_id", f"{_SCHEMA}.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_payment__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            [f"{_SCHEMA}.billing_invoice.tenant_id", f"{_SCHEMA}.billing_invoice.id"],
            ondelete="SET NULL",
            name="fkx_billing_payment__tenant_invoice",
        ),

        sa.CheckConstraint("length(btrim(currency)) = 3", name="ck_billing_payment__currency_len3"),
        sa.CheckConstraint("amount >= 0", name="ck_billing_payment__amount_nonneg"),
        sa.CheckConstraint("provider IS NULL OR length(btrim(provider)) > 0", name="ck_billing_payment__provider_nonempty_if_set"),
        sa.CheckConstraint("external_ref IS NULL OR length(btrim(external_ref)) > 0", name="ck_billing_payment__external_ref_nonempty_if_set"),

        sa.PrimaryKeyConstraint("id", name="pk_billing_payment"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_payment__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_payment_tenant_id"), "billing_payment", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_payment_account_id"), "billing_payment", ["account_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_payment_invoice_id"), "billing_payment", ["invoice_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_payment_status"), "billing_payment", ["status"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_payment_currency"), "billing_payment", ["currency"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_payment_provider"), "billing_payment", ["provider"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_payment_external_ref"), "billing_payment", ["external_ref"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_payment__tenant_account", "billing_payment", ["tenant_id", "account_id"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_usage_event
    # ------------------------------
    op.create_table(
        "billing_usage_event",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=True),

        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("quantity", sa.BigInteger(), server_default=sa.text("0"), nullable=False),

        sa.Column("status", billing_usage_event_status, server_default=sa.text("'recorded'"), nullable=False),

        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_usage_event__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [f"{_SCHEMA}.billing_account.tenant_id", f"{_SCHEMA}.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_usage_event__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            [f"{_SCHEMA}.billing_subscription.tenant_id", f"{_SCHEMA}.billing_subscription.id"],
            ondelete="SET NULL",
            name="fkx_billing_usage_event__tenant_subscription",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "price_id"],
            [f"{_SCHEMA}.billing_price.tenant_id", f"{_SCHEMA}.billing_price.id"],
            ondelete="SET NULL",
            name="fkx_billing_usage_event__tenant_price",
        ),

        sa.CheckConstraint("quantity >= 0", name="ck_billing_usage_event__quantity_nonneg"),
        sa.CheckConstraint("external_ref IS NULL OR length(btrim(external_ref)) > 0", name="ck_billing_usage_event__external_ref_nonempty_if_set"),

        sa.PrimaryKeyConstraint("id", name="pk_billing_usage_event"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_usage_event__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_usage_event_tenant_id"), "billing_usage_event", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_usage_event_account_id"), "billing_usage_event", ["account_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_usage_event_subscription_id"), "billing_usage_event", ["subscription_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_usage_event_price_id"), "billing_usage_event", ["price_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_usage_event_occurred_at"), "billing_usage_event", ["occurred_at"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_usage_event_status"), "billing_usage_event", ["status"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_usage_event_external_ref"), "billing_usage_event", ["external_ref"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_usage_event__tenant_account_occurred", "billing_usage_event", ["tenant_id", "account_id", "occurred_at"], unique=False, schema=_SCHEMA)

    # ------------------------------
    # billing_ledger_entry
    # ------------------------------
    op.create_table(
        "billing_ledger_entry",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),

        sa.Column("tenant_id", sa.Uuid(), nullable=False),

        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("payment_id", sa.Uuid(), nullable=True),

        sa.Column("direction", billing_ledger_direction, server_default=sa.text("'debit'"), nullable=False),

        sa.Column("currency", postgresql.CITEXT(length=3), nullable=False),
        sa.Column("amount", sa.BigInteger(), server_default=sa.text("0"), nullable=False),

        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),

        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_ledger_entry__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [f"{_SCHEMA}.billing_account.tenant_id", f"{_SCHEMA}.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_ledger_entry__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            [f"{_SCHEMA}.billing_invoice.tenant_id", f"{_SCHEMA}.billing_invoice.id"],
            ondelete="SET NULL",
            name="fkx_billing_ledger_entry__tenant_invoice",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            [f"{_SCHEMA}.billing_payment.tenant_id", f"{_SCHEMA}.billing_payment.id"],
            ondelete="SET NULL",
            name="fkx_billing_ledger_entry__tenant_payment",
        ),

        sa.CheckConstraint("length(btrim(currency)) = 3", name="ck_billing_ledger_entry__currency_len3"),
        sa.CheckConstraint("amount >= 0", name="ck_billing_ledger_entry__amount_nonneg"),
        sa.CheckConstraint("external_ref IS NULL OR length(btrim(external_ref)) > 0", name="ck_billing_ledger_entry__external_ref_nonempty_if_set"),

        sa.PrimaryKeyConstraint("id", name="pk_billing_ledger_entry"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_ledger_entry__tenant_id_id"),

        schema=_SCHEMA,
    )
    op.create_index(op.f("ix_mugen_billing_ledger_entry_tenant_id"), "billing_ledger_entry", ["tenant_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_account_id"), "billing_ledger_entry", ["account_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_invoice_id"), "billing_ledger_entry", ["invoice_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_payment_id"), "billing_ledger_entry", ["payment_id"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_direction"), "billing_ledger_entry", ["direction"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_currency"), "billing_ledger_entry", ["currency"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_occurred_at"), "billing_ledger_entry", ["occurred_at"], unique=False, schema=_SCHEMA)
    op.create_index(op.f("ix_mugen_billing_ledger_entry_external_ref"), "billing_ledger_entry", ["external_ref"], unique=False, schema=_SCHEMA)
    op.create_index("ix_billing_ledger_entry__tenant_account_occurred", "billing_ledger_entry", ["tenant_id", "account_id", "occurred_at"], unique=False, schema=_SCHEMA)


def downgrade() -> None:
    # Drop billing tables (reverse dependency order).
    op.drop_table("billing_ledger_entry", schema=_SCHEMA)
    op.drop_table("billing_usage_event", schema=_SCHEMA)
    op.drop_table("billing_payment", schema=_SCHEMA)
    op.drop_table("billing_invoice_line", schema=_SCHEMA)
    op.drop_table("billing_invoice", schema=_SCHEMA)
    op.drop_table("billing_subscription", schema=_SCHEMA)
    op.drop_table("billing_price", schema=_SCHEMA)
    op.drop_table("billing_product", schema=_SCHEMA)
    op.drop_table("billing_account", schema=_SCHEMA)

    # Drop enum types (if no longer referenced).
    bind = op.get_bind()
    for enum_name in (
        "billing_ledger_direction",
        "billing_payment_status",
        "billing_invoice_status",
        "billing_usage_event_status",
        "billing_subscription_status",
        "billing_interval_unit",
        "billing_price_type",
    ):
        postgresql.ENUM(name=enum_name, schema=_SCHEMA).drop(bind, checkfirst=True)
