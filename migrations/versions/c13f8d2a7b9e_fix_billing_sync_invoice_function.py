"""Fix billing invoice sync function enum cast and status literals.

Revision ID: c13f8d2a7b9e
Revises: b9f7c2d4e6a1
Create Date: 2026-02-13 15:33:00.000000

"""

from typing import Sequence, Union

from alembic import op
from migrations.schema_contract import rewrite_mugen_schema_sql
from migrations.schema_contract import resolve_runtime_schema

# revision identifiers, used by Alembic.
revision: str = "c13f8d2a7b9e"
down_revision: Union[str, Sequence[str], None] = "b9f7c2d4e6a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = resolve_runtime_schema()


def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _execute(statement) -> None:
    if isinstance(statement, str):
        op.execute(_sql(statement))
        return
    op.execute(statement)


def upgrade() -> None:
    """Apply corrected billing invoice sync function."""
    _execute(
        """
        CREATE OR REPLACE FUNCTION mugen.fn_billing_sync_invoice_from_allocations(
            p_tenant_id UUID,
            p_invoice_id UUID
        )
        RETURNS VOID
        LANGUAGE plpgsql
        AS
        $fn_billing_sync_invoice_from_allocations$
        DECLARE
            v_total_amount BIGINT;
            v_status TEXT;
            v_amount_due BIGINT;
            v_paid_at TIMESTAMPTZ;
            v_alloc_total BIGINT;
            v_next_due BIGINT;
            v_next_status TEXT;
            v_next_paid_at TIMESTAMPTZ;
        BEGIN
            SELECT inv.total_amount, inv.status::TEXT, inv.amount_due, inv.paid_at
            INTO v_total_amount, v_status, v_amount_due, v_paid_at
            FROM mugen.billing_invoice inv
            WHERE inv.tenant_id = p_tenant_id
              AND inv.id = p_invoice_id
            FOR UPDATE;

            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT COALESCE(SUM(pa.amount), 0)
            INTO v_alloc_total
            FROM mugen.billing_payment_allocation pa
            WHERE pa.tenant_id = p_tenant_id
              AND pa.invoice_id = p_invoice_id;

            IF v_status = 'void' THEN
                v_next_due := 0;
                v_next_status := v_status;
                v_next_paid_at := v_paid_at;
            ELSE
                v_next_due := GREATEST(v_total_amount - v_alloc_total, 0);
                v_next_status := v_status;
                v_next_paid_at := v_paid_at;

                IF v_status IN ('issued', 'paid') THEN
                    IF v_next_due = 0 THEN
                        v_next_status := 'paid';
                        v_next_paid_at := COALESCE(v_paid_at, now());
                    ELSIF v_status = 'paid' THEN
                        v_next_status := 'issued';
                        v_next_paid_at := NULL;
                    END IF;
                END IF;
            END IF;

            UPDATE mugen.billing_invoice
            SET amount_due = v_next_due,
                status = v_next_status::mugen.billing_invoice_status,
                paid_at = v_next_paid_at
            WHERE tenant_id = p_tenant_id
              AND id = p_invoice_id
              AND (
                  amount_due IS DISTINCT FROM v_next_due
                  OR status::TEXT IS DISTINCT FROM v_next_status
                  OR paid_at IS DISTINCT FROM v_next_paid_at
              );
        END
        $fn_billing_sync_invoice_from_allocations$;
        """
    )


def downgrade() -> None:
    """
    Keep the corrected function in place.

    Downgrading this revision should not reintroduce a known-broken function body.
    """
    return
