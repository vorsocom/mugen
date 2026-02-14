"""billing runs, adjustments, and meter code normalization

Revision ID: f7b1c2d3e4a5
Revises: d8a9f3c1e52b
Create Date: 2026-02-11 16:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "f7b1c2d3e4a5"
down_revision: Union[str, None] = "d8a9f3c1e52b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    billing_run_status = postgresql.ENUM(
        "pending",
        "running",
        "succeeded",
        "failed",
        "canceled",
        name="billing_run_status",
        schema="mugen",
        create_type=False,
    )
    billing_credit_note_status = postgresql.ENUM(
        "draft",
        "issued",
        "void",
        name="billing_credit_note_status",
        schema="mugen",
        create_type=False,
    )
    billing_adjustment_kind = postgresql.ENUM(
        "credit",
        "debit",
        name="billing_adjustment_kind",
        schema="mugen",
        create_type=False,
    )
    billing_run_status.create(op.get_bind(), checkfirst=True)
    billing_credit_note_status.create(op.get_bind(), checkfirst=True)
    billing_adjustment_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "billing_run",
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
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("run_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            billing_run_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("idempotency_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_run__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["mugen.billing_account.tenant_id", "mugen.billing_account.id"],
            ondelete="SET NULL",
            name="fkx_billing_run__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            ["mugen.billing_subscription.tenant_id", "mugen.billing_subscription.id"],
            ondelete="SET NULL",
            name="fkx_billing_run__tenant_subscription",
        ),
        sa.CheckConstraint(
            "length(btrim(run_type)) > 0",
            name="ck_billing_run__run_type_nonempty",
        ),
        sa.CheckConstraint(
            "period_end > period_start",
            name="ck_billing_run__period_bounds",
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_billing_run__idempotency_key_nonempty",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_run__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_run"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_billing_run__tenant_id_id"),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_tenant_id"),
        "billing_run",
        ["tenant_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_account_id"),
        "billing_run",
        ["account_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_subscription_id"),
        "billing_run",
        ["subscription_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_run_type"),
        "billing_run",
        ["run_type"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_period_start"),
        "billing_run",
        ["period_start"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_period_end"),
        "billing_run",
        ["period_end"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_status"),
        "billing_run",
        ["status"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_idempotency_key"),
        "billing_run",
        ["idempotency_key"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_run_external_ref"),
        "billing_run",
        ["external_ref"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ux_billing_run__tenant_idempotency_key",
        "billing_run",
        ["tenant_id", "idempotency_key"],
        unique=True,
        schema="mugen",
    )
    op.create_index(
        "ix_billing_run__tenant_run_type_period",
        "billing_run",
        ["tenant_id", "run_type", "period_start"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ux_billing_run__tenant_external_ref",
        "billing_run",
        ["tenant_id", "external_ref"],
        unique=True,
        schema="mugen",
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.create_table(
        "billing_credit_note",
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
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            billing_credit_note_status,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("number", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("currency", postgresql.CITEXT(length=3), nullable=False),
        sa.Column(
            "total_amount",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_credit_note__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["mugen.billing_account.tenant_id", "mugen.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_credit_note__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["mugen.billing_invoice.tenant_id", "mugen.billing_invoice.id"],
            ondelete="SET NULL",
            name="fkx_billing_credit_note__tenant_invoice",
        ),
        sa.CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_credit_note__currency_len3",
        ),
        sa.CheckConstraint(
            "number IS NULL OR length(btrim(number)) > 0",
            name="ck_billing_credit_note__number_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "total_amount >= 0",
            name="ck_billing_credit_note__total_nonneg",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_credit_note__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_credit_note"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_credit_note__tenant_id_id",
        ),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_tenant_id"),
        "billing_credit_note",
        ["tenant_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_account_id"),
        "billing_credit_note",
        ["account_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_invoice_id"),
        "billing_credit_note",
        ["invoice_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_status"),
        "billing_credit_note",
        ["status"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_number"),
        "billing_credit_note",
        ["number"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_currency"),
        "billing_credit_note",
        ["currency"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_credit_note_external_ref"),
        "billing_credit_note",
        ["external_ref"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ix_billing_credit_note__tenant_account",
        "billing_credit_note",
        ["tenant_id", "account_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ix_billing_credit_note__tenant_invoice",
        "billing_credit_note",
        ["tenant_id", "invoice_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ux_billing_credit_note__tenant_number",
        "billing_credit_note",
        ["tenant_id", "number"],
        unique=True,
        schema="mugen",
        postgresql_where=sa.text("number IS NOT NULL"),
    )
    op.create_index(
        "ux_billing_credit_note__tenant_external_ref",
        "billing_credit_note",
        ["tenant_id", "external_ref"],
        unique=True,
        schema="mugen",
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.create_table(
        "billing_adjustment",
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
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("credit_note_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            billing_adjustment_kind,
            server_default=sa.text("'credit'"),
            nullable=False,
        ),
        sa.Column("currency", postgresql.CITEXT(length=3), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_adjustment__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            ["mugen.billing_account.tenant_id", "mugen.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_adjustment__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "invoice_id"],
            ["mugen.billing_invoice.tenant_id", "mugen.billing_invoice.id"],
            ondelete="SET NULL",
            name="fkx_billing_adjustment__tenant_invoice",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "credit_note_id"],
            ["mugen.billing_credit_note.tenant_id", "mugen.billing_credit_note.id"],
            ondelete="SET NULL",
            name="fkx_billing_adjustment__tenant_credit_note",
        ),
        sa.CheckConstraint(
            "length(btrim(currency)) = 3",
            name="ck_billing_adjustment__currency_len3",
        ),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_billing_adjustment__amount_nonneg",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_billing_adjustment__reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_adjustment__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_adjustment"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_adjustment__tenant_id_id",
        ),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_tenant_id"),
        "billing_adjustment",
        ["tenant_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_account_id"),
        "billing_adjustment",
        ["account_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_invoice_id"),
        "billing_adjustment",
        ["invoice_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_credit_note_id"),
        "billing_adjustment",
        ["credit_note_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_kind"),
        "billing_adjustment",
        ["kind"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_currency"),
        "billing_adjustment",
        ["currency"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_occurred_at"),
        "billing_adjustment",
        ["occurred_at"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_adjustment_external_ref"),
        "billing_adjustment",
        ["external_ref"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ix_billing_adjustment__tenant_account_occurred",
        "billing_adjustment",
        ["tenant_id", "account_id", "occurred_at"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ix_billing_adjustment__tenant_invoice",
        "billing_adjustment",
        ["tenant_id", "invoice_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ix_billing_adjustment__tenant_credit_note",
        "billing_adjustment",
        ["tenant_id", "credit_note_id"],
        unique=False,
        schema="mugen",
    )
    op.create_index(
        "ux_billing_adjustment__tenant_external_ref",
        "billing_adjustment",
        ["tenant_id", "external_ref"],
        unique=True,
        schema="mugen",
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )

    op.add_column(
        "billing_price",
        sa.Column("meter_code", postgresql.CITEXT(length=64), nullable=True),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_price_meter_code"),
        "billing_price",
        ["meter_code"],
        unique=False,
        schema="mugen",
    )
    op.execute(
        """
        UPDATE mugen.billing_price
        SET meter_code = COALESCE(NULLIF(usage_unit, ''), code)
        WHERE meter_code IS NULL;
        """
    )
    op.alter_column(
        "billing_price",
        "meter_code",
        existing_type=postgresql.CITEXT(length=64),
        nullable=False,
        schema="mugen",
    )
    op.create_check_constraint(
        "ck_billing_price__meter_code_nonempty",
        "billing_price",
        "length(btrim(meter_code)) > 0",
        schema="mugen",
    )
    op.create_index(
        "ix_billing_price__tenant_meter_code",
        "billing_price",
        ["tenant_id", "meter_code"],
        unique=False,
        schema="mugen",
    )

    op.add_column(
        "billing_usage_event",
        sa.Column("meter_code", postgresql.CITEXT(length=64), nullable=True),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_billing_usage_event_meter_code"),
        "billing_usage_event",
        ["meter_code"],
        unique=False,
        schema="mugen",
    )
    op.execute(
        """
        UPDATE mugen.billing_usage_event ue
        SET meter_code = COALESCE(
            NULLIF(bp.meter_code, ''),
            NULLIF(bp.usage_unit, ''),
            bp.code
        )
        FROM mugen.billing_price bp
        WHERE ue.tenant_id = bp.tenant_id
          AND ue.price_id = bp.id
          AND ue.meter_code IS NULL;
        """
    )
    op.execute(
        """
        UPDATE mugen.billing_usage_event
        SET meter_code = 'unmapped'
        WHERE meter_code IS NULL;
        """
    )
    op.alter_column(
        "billing_usage_event",
        "meter_code",
        existing_type=postgresql.CITEXT(length=64),
        nullable=False,
        schema="mugen",
    )
    op.create_check_constraint(
        "ck_billing_usage_event__meter_code_nonempty",
        "billing_usage_event",
        "length(btrim(meter_code)) > 0",
        schema="mugen",
    )
    op.create_index(
        "ix_billing_usage_event__tenant_account_meter_occurred",
        "billing_usage_event",
        ["tenant_id", "account_id", "meter_code", "occurred_at"],
        unique=False,
        schema="mugen",
    )

    op.execute(
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION mugen.tg_billing_payment_allocation_sync_invoice()
            RETURNS TRIGGER
            LANGUAGE plpgsql
        AS
        $tg_billing_payment_allocation_sync_invoice$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM mugen.fn_billing_sync_invoice_from_allocations(
                    NEW.tenant_id,
                    NEW.invoice_id
                );
                RETURN NEW;
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF OLD.tenant_id = NEW.tenant_id
                   AND OLD.invoice_id = NEW.invoice_id THEN
                    PERFORM mugen.fn_billing_sync_invoice_from_allocations(
                        NEW.tenant_id,
                        NEW.invoice_id
                    );
                ELSE
                    PERFORM mugen.fn_billing_sync_invoice_from_allocations(
                        OLD.tenant_id,
                        OLD.invoice_id
                    );
                    PERFORM mugen.fn_billing_sync_invoice_from_allocations(
                        NEW.tenant_id,
                        NEW.invoice_id
                    );
                END IF;
                RETURN NEW;
            END IF;

            PERFORM mugen.fn_billing_sync_invoice_from_allocations(
                OLD.tenant_id,
                OLD.invoice_id
            );
            RETURN OLD;
        END
        $tg_billing_payment_allocation_sync_invoice$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER tr_billing_payment_allocation_sync_invoice
        AFTER INSERT OR UPDATE OR DELETE ON mugen.billing_payment_allocation
        FOR EACH ROW EXECUTE FUNCTION mugen.tg_billing_payment_allocation_sync_invoice();
        """
    )
    op.execute(
        """
        DO
        $do_billing_sync_existing_invoices$
        DECLARE
            rec RECORD;
        BEGIN
            FOR rec IN
                SELECT DISTINCT tenant_id, invoice_id
                FROM mugen.billing_payment_allocation
            LOOP
                PERFORM mugen.fn_billing_sync_invoice_from_allocations(
                    rec.tenant_id,
                    rec.invoice_id
                );
            END LOOP;
        END
        $do_billing_sync_existing_invoices$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__billing_run
        BEFORE UPDATE ON mugen.billing_run
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__billing_credit_note
        BEFORE UPDATE ON mugen.billing_credit_note
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__billing_adjustment
        BEFORE UPDATE ON mugen.billing_adjustment
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS tr_billing_payment_allocation_sync_invoice ON mugen.billing_payment_allocation;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS mugen.tg_billing_payment_allocation_sync_invoice();"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS mugen.fn_billing_sync_invoice_from_allocations(UUID, UUID);"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__billing_adjustment ON mugen.billing_adjustment;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__billing_credit_note ON mugen.billing_credit_note;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__billing_run ON mugen.billing_run;"
    )

    op.drop_index(
        "ix_billing_usage_event__tenant_account_meter_occurred",
        table_name="billing_usage_event",
        schema="mugen",
    )
    op.drop_constraint(
        "ck_billing_usage_event__meter_code_nonempty",
        "billing_usage_event",
        schema="mugen",
        type_="check",
    )
    op.drop_index(
        op.f("ix_mugen_billing_usage_event_meter_code"),
        table_name="billing_usage_event",
        schema="mugen",
    )
    op.drop_column("billing_usage_event", "meter_code", schema="mugen")

    op.drop_index(
        "ix_billing_price__tenant_meter_code",
        table_name="billing_price",
        schema="mugen",
    )
    op.drop_constraint(
        "ck_billing_price__meter_code_nonempty",
        "billing_price",
        schema="mugen",
        type_="check",
    )
    op.drop_index(
        op.f("ix_mugen_billing_price_meter_code"),
        table_name="billing_price",
        schema="mugen",
    )
    op.drop_column("billing_price", "meter_code", schema="mugen")

    op.drop_index(
        "ux_billing_adjustment__tenant_external_ref",
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        "ix_billing_adjustment__tenant_credit_note",
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        "ix_billing_adjustment__tenant_invoice",
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        "ix_billing_adjustment__tenant_account_occurred",
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_external_ref"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_occurred_at"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_currency"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_kind"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_credit_note_id"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_invoice_id"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_account_id"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_adjustment_tenant_id"),
        table_name="billing_adjustment",
        schema="mugen",
    )
    op.drop_table("billing_adjustment", schema="mugen")

    op.drop_index(
        "ux_billing_credit_note__tenant_external_ref",
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        "ux_billing_credit_note__tenant_number",
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        "ix_billing_credit_note__tenant_invoice",
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        "ix_billing_credit_note__tenant_account",
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_external_ref"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_currency"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_number"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_status"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_invoice_id"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_account_id"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_credit_note_tenant_id"),
        table_name="billing_credit_note",
        schema="mugen",
    )
    op.drop_table("billing_credit_note", schema="mugen")

    op.drop_index(
        "ux_billing_run__tenant_external_ref",
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        "ix_billing_run__tenant_run_type_period",
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        "ux_billing_run__tenant_idempotency_key",
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_external_ref"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_idempotency_key"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_status"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_period_end"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_period_start"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_run_type"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_subscription_id"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_account_id"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_tenant_id"),
        table_name="billing_run",
        schema="mugen",
    )
    op.drop_table("billing_run", schema="mugen")

    bind = op.get_bind()
    for enum_name in (
        "billing_adjustment_kind",
        "billing_credit_note_status",
        "billing_run_status",
    ):
        postgresql.ENUM(name=enum_name, schema="mugen").drop(bind, checkfirst=True)
