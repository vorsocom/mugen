"""billing constraints and indexes

Revision ID: a655f4dcaa93
Revises: 06b5096e3363
Create Date: 2026-01-14 16:13:11.150344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "a655f4dcaa93"
down_revision: Union[str, None] = "06b5096e3363"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    # Uniqueness for natural keys / external references, scoped by tenant.
    op.create_index(
        "ux_billing_account__tenant_code_active",
        "billing_account",
        ["tenant_id", "code"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_index(
        "ux_billing_product__tenant_code_active",
        "billing_product",
        ["tenant_id", "code"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_index(
        "ux_billing_price__tenant_code_active",
        "billing_price",
        ["tenant_id", "code"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_index(
        "ux_billing_subscription__tenant_external_ref_active",
        "billing_subscription",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("external_ref IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_index(
        "ux_billing_invoice__tenant_number_active",
        "billing_invoice",
        ["tenant_id", "number"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("number IS NOT NULL AND deleted_at IS NULL"),
    )

    op.create_index(
        "ux_billing_payment__tenant_external_ref",
        "billing_payment",
        ["tenant_id", "provider", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.create_index(
        "ux_billing_usage_event__tenant_external_ref",
        "billing_usage_event",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.create_index(
        "ux_billing_ledger_entry__tenant_external_ref",
        "billing_ledger_entry",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_billing_ledger_entry__tenant_external_ref", table_name="billing_ledger_entry", schema=_SCHEMA)
    op.drop_index("ux_billing_usage_event__tenant_external_ref", table_name="billing_usage_event", schema=_SCHEMA)
    op.drop_index("ux_billing_payment__tenant_external_ref", table_name="billing_payment", schema=_SCHEMA)
    op.drop_index("ux_billing_invoice__tenant_number_active", table_name="billing_invoice", schema=_SCHEMA)
    op.drop_index("ux_billing_subscription__tenant_external_ref_active", table_name="billing_subscription", schema=_SCHEMA)
    op.drop_index("ux_billing_price__tenant_code_active", table_name="billing_price", schema=_SCHEMA)
    op.drop_index("ux_billing_product__tenant_code_active", table_name="billing_product", schema=_SCHEMA)
    op.drop_index("ux_billing_account__tenant_code_active", table_name="billing_account", schema=_SCHEMA)
