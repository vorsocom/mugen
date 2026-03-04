"""billing payment allocations

Revision ID: 9c4211adf09d
Revises: a655f4dcaa93
Create Date: 2026-02-11 12:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import rewrite_mugen_schema_sql
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def _execute(statement) -> None:
    if isinstance(statement, str):
        op.execute(_sql(statement))
        return
    op.execute(statement)


# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "9c4211adf09d"
down_revision: Union[str, None] = "a655f4dcaa93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.create_table(
        "billing_payment_allocation",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=_sql_text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=_sql_text("1"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "allocated_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_payment_allocation__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "payment_id"],
            [f"{_SCHEMA}.billing_payment.tenant_id", f"{_SCHEMA}.billing_payment.id"],
            ondelete="RESTRICT",
            name="fkx_billing_payment_allocation__tenant_payment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            [f"{_SCHEMA}.billing_invoice.tenant_id", f"{_SCHEMA}.billing_invoice.id"],
            ondelete="RESTRICT",
            name="fkx_billing_payment_allocation__tenant_invoice",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_billing_payment_allocation__amount_positive",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_payment_allocation__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_payment_allocation"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_payment_allocation__tenant_id_id",
        ),
        schema=_SCHEMA,
    )

    op.create_index(
        op.f("ix_mugen_billing_payment_allocation_tenant_id"),
        "billing_payment_allocation",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_payment_allocation_payment_id"),
        "billing_payment_allocation",
        ["payment_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_payment_allocation_invoice_id"),
        "billing_payment_allocation",
        ["invoice_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_payment_allocation_allocated_at"),
        "billing_payment_allocation",
        ["allocated_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_payment_allocation_external_ref"),
        "billing_payment_allocation",
        ["external_ref"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_payment_allocation__tenant_payment",
        "billing_payment_allocation",
        ["tenant_id", "payment_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_payment_allocation__tenant_invoice",
        "billing_payment_allocation",
        ["tenant_id", "invoice_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_billing_payment_allocation__tenant_external_ref",
        "billing_payment_allocation",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("external_ref IS NOT NULL"),
    )

    _execute(
        """
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__billing_payment_allocation
        BEFORE UPDATE ON mugen.billing_payment_allocation
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
        """
    )


def downgrade() -> None:
    _execute(
        "DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__billing_payment_allocation ON mugen.billing_payment_allocation;"
    )
    op.drop_index(
        "ux_billing_payment_allocation__tenant_external_ref",
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_payment_allocation__tenant_invoice",
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_payment_allocation__tenant_payment",
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_payment_allocation_external_ref"),
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_payment_allocation_allocated_at"),
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_payment_allocation_invoice_id"),
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_payment_allocation_payment_id"),
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_payment_allocation_tenant_id"),
        table_name="billing_payment_allocation",
        schema=_SCHEMA,
    )
    op.drop_table("billing_payment_allocation", schema=_SCHEMA)
