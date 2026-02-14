"""billing touch triggers

Revision ID: 06b5096e3363
Revises: bf491cdca026
Create Date: 2026-01-14 16:13:11.150344

"""
from typing import Sequence, Union

from alembic import op

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "06b5096e3363"
down_revision: Union[str, None] = "bf491cdca026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure the trigger function exists (shared utility).
    op.execute("CREATE SCHEMA IF NOT EXISTS util;")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION util.tg_touch_updated_at_row_version()
            RETURNS TRIGGER
            LANGUAGE plpgsql
        AS
        $tg_touch_updated_at_row_version$
        BEGIN
            NEW.updated_at := now();
            NEW.row_version := OLD.row_version + 1;
            RETURN NEW;
        END
        $tg_touch_updated_at_row_version$;
        """
    )

    # Create touch triggers for billing tables.
    for tbl in (
        "billing_account",
        "billing_product",
        "billing_price",
        "billing_subscription",
        "billing_invoice",
        "billing_invoice_line",
        "billing_payment",
        "billing_usage_event",
        "billing_ledger_entry",
    ):
        op.execute(
            f"""
            CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__{tbl}
            BEFORE UPDATE ON mugen.{tbl}
            FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
            """
        )


def downgrade() -> None:
    # Drop touch triggers for billing tables.
    for tbl in (
        "billing_ledger_entry",
        "billing_usage_event",
        "billing_payment",
        "billing_invoice_line",
        "billing_invoice",
        "billing_subscription",
        "billing_price",
        "billing_product",
        "billing_account",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__{tbl} ON mugen.{tbl};"
        )
