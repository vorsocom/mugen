"""billing entitlements and usage allocations

Revision ID: d8a9f3c1e52b
Revises: 9c4211adf09d
Create Date: 2026-02-11 13:10:00.000000

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
revision: str = "d8a9f3c1e52b"
down_revision: Union[str, None] = "9c4211adf09d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.create_table(
        "billing_entitlement_bucket",
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
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("price_id", sa.Uuid(), nullable=True),
        sa.Column("meter_code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "included_quantity",
            sa.BigInteger(),
            server_default=_sql_text("0"),
            nullable=False,
        ),
        sa.Column(
            "consumed_quantity",
            sa.BigInteger(),
            server_default=_sql_text("0"),
            nullable=False,
        ),
        sa.Column(
            "rollover_quantity",
            sa.BigInteger(),
            server_default=_sql_text("0"),
            nullable=False,
        ),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_entitlement_bucket__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [f"{_SCHEMA}.billing_account.tenant_id", f"{_SCHEMA}.billing_account.id"],
            ondelete="RESTRICT",
            name="fkx_billing_entitlement_bucket__tenant_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            [f"{_SCHEMA}.billing_subscription.tenant_id", f"{_SCHEMA}.billing_subscription.id"],
            ondelete="SET NULL",
            name="fkx_billing_entitlement_bucket__tenant_subscription",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "price_id"],
            [f"{_SCHEMA}.billing_price.tenant_id", f"{_SCHEMA}.billing_price.id"],
            ondelete="SET NULL",
            name="fkx_billing_entitlement_bucket__tenant_price",
        ),
        sa.CheckConstraint(
            "length(btrim(meter_code)) > 0",
            name="ck_billing_entitlement_bucket__meter_code_nonempty",
        ),
        sa.CheckConstraint(
            "period_end > period_start",
            name="ck_billing_entitlement_bucket__period_bounds",
        ),
        sa.CheckConstraint(
            "included_quantity >= 0",
            name="ck_billing_entitlement_bucket__included_nonneg",
        ),
        sa.CheckConstraint(
            "consumed_quantity >= 0",
            name="ck_billing_entitlement_bucket__consumed_nonneg",
        ),
        sa.CheckConstraint(
            "rollover_quantity >= 0",
            name="ck_billing_entitlement_bucket__rollover_nonneg",
        ),
        sa.CheckConstraint(
            "consumed_quantity <= (included_quantity + rollover_quantity)",
            name="ck_billing_entitlement_bucket__consumed_within_capacity",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_entitlement_bucket__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_entitlement_bucket"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_entitlement_bucket__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_tenant_id"),
        "billing_entitlement_bucket",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_account_id"),
        "billing_entitlement_bucket",
        ["account_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_subscription_id"),
        "billing_entitlement_bucket",
        ["subscription_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_price_id"),
        "billing_entitlement_bucket",
        ["price_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_meter_code"),
        "billing_entitlement_bucket",
        ["meter_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_period_start"),
        "billing_entitlement_bucket",
        ["period_start"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_period_end"),
        "billing_entitlement_bucket",
        ["period_end"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_entitlement_bucket_external_ref"),
        "billing_entitlement_bucket",
        ["external_ref"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_entitlement_bucket__tenant_account_meter_period",
        "billing_entitlement_bucket",
        ["tenant_id", "account_id", "meter_code", "period_start"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_entitlement_bucket__tenant_subscription_meter_period",
        "billing_entitlement_bucket",
        ["tenant_id", "subscription_id", "meter_code", "period_start"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_billing_entitlement_bucket__tenant_external_ref",
        "billing_entitlement_bucket",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("external_ref IS NOT NULL"),
    )

    op.create_table(
        "billing_usage_allocation",
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
        sa.Column("usage_event_id", sa.Uuid(), nullable=False),
        sa.Column("entitlement_bucket_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_quantity", sa.BigInteger(), nullable=False),
        sa.Column("external_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_billing_usage_allocation__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "usage_event_id"],
            [f"{_SCHEMA}.billing_usage_event.tenant_id", f"{_SCHEMA}.billing_usage_event.id"],
            ondelete="RESTRICT",
            name="fkx_billing_usage_allocation__tenant_usage_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "entitlement_bucket_id"],
            [f"{_SCHEMA}.billing_entitlement_bucket.tenant_id", f"{_SCHEMA}.billing_entitlement_bucket.id"],
            ondelete="RESTRICT",
            name="fkx_billing_usage_allocation__tenant_entitlement_bucket",
        ),
        sa.CheckConstraint(
            "allocated_quantity > 0",
            name="ck_billing_usage_allocation__allocated_positive",
        ),
        sa.CheckConstraint(
            "external_ref IS NULL OR length(btrim(external_ref)) > 0",
            name="ck_billing_usage_allocation__external_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_usage_allocation"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_billing_usage_allocation__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "usage_event_id",
            "entitlement_bucket_id",
            name="ux_billing_usage_allocation__tenant_usage_event_bucket",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_usage_allocation_tenant_id"),
        "billing_usage_allocation",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_usage_allocation_usage_event_id"),
        "billing_usage_allocation",
        ["usage_event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_usage_allocation_entitlement_bucket_id"),
        "billing_usage_allocation",
        ["entitlement_bucket_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_usage_allocation_external_ref"),
        "billing_usage_allocation",
        ["external_ref"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_usage_allocation__tenant_usage_event",
        "billing_usage_allocation",
        ["tenant_id", "usage_event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_usage_allocation__tenant_entitlement_bucket",
        "billing_usage_allocation",
        ["tenant_id", "entitlement_bucket_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_billing_usage_allocation__tenant_external_ref",
        "billing_usage_allocation",
        ["tenant_id", "external_ref"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("external_ref IS NOT NULL"),
    )

    _execute(
        """
        CREATE OR REPLACE FUNCTION mugen.tg_billing_usage_allocation_rollup_consumed()
            RETURNS TRIGGER
            LANGUAGE plpgsql
        AS
        $tg_billing_usage_allocation_rollup_consumed$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE mugen.billing_entitlement_bucket
                SET consumed_quantity = consumed_quantity + NEW.allocated_quantity
                WHERE tenant_id = NEW.tenant_id
                  AND id = NEW.entitlement_bucket_id;
                RETURN NEW;
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF NEW.tenant_id = OLD.tenant_id
                   AND NEW.entitlement_bucket_id = OLD.entitlement_bucket_id THEN
                    UPDATE mugen.billing_entitlement_bucket
                    SET consumed_quantity = (
                        consumed_quantity
                        - OLD.allocated_quantity
                        + NEW.allocated_quantity
                    )
                    WHERE tenant_id = NEW.tenant_id
                      AND id = NEW.entitlement_bucket_id;
                ELSE
                    UPDATE mugen.billing_entitlement_bucket
                    SET consumed_quantity = consumed_quantity - OLD.allocated_quantity
                    WHERE tenant_id = OLD.tenant_id
                      AND id = OLD.entitlement_bucket_id;

                    UPDATE mugen.billing_entitlement_bucket
                    SET consumed_quantity = consumed_quantity + NEW.allocated_quantity
                    WHERE tenant_id = NEW.tenant_id
                      AND id = NEW.entitlement_bucket_id;
                END IF;
                RETURN NEW;
            END IF;

            UPDATE mugen.billing_entitlement_bucket
            SET consumed_quantity = consumed_quantity - OLD.allocated_quantity
            WHERE tenant_id = OLD.tenant_id
              AND id = OLD.entitlement_bucket_id;
            RETURN OLD;
        END
        $tg_billing_usage_allocation_rollup_consumed$;
        """
    )
    _execute(
        """
        CREATE OR REPLACE TRIGGER tr_billing_usage_allocation_rollup_consumed
        AFTER INSERT OR UPDATE OR DELETE ON mugen.billing_usage_allocation
        FOR EACH ROW EXECUTE FUNCTION mugen.tg_billing_usage_allocation_rollup_consumed();
        """
    )

    _execute(
        """
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__billing_entitlement_bucket
        BEFORE UPDATE ON mugen.billing_entitlement_bucket
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
        """
    )
    _execute(
        """
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__billing_usage_allocation
        BEFORE UPDATE ON mugen.billing_usage_allocation
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
        """
    )


def downgrade() -> None:
    _execute(
        "DROP TRIGGER IF EXISTS tr_billing_usage_allocation_rollup_consumed ON mugen.billing_usage_allocation;"
    )
    _execute(
        "DROP FUNCTION IF EXISTS mugen.tg_billing_usage_allocation_rollup_consumed();"
    )

    _execute(
        "DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__billing_usage_allocation ON mugen.billing_usage_allocation;"
    )
    _execute(
        "DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__billing_entitlement_bucket ON mugen.billing_entitlement_bucket;"
    )

    op.drop_index(
        "ux_billing_usage_allocation__tenant_external_ref",
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_usage_allocation__tenant_entitlement_bucket",
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_usage_allocation__tenant_usage_event",
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_usage_allocation_external_ref"),
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_usage_allocation_entitlement_bucket_id"),
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_usage_allocation_usage_event_id"),
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_usage_allocation_tenant_id"),
        table_name="billing_usage_allocation",
        schema=_SCHEMA,
    )
    op.drop_table("billing_usage_allocation", schema=_SCHEMA)

    op.drop_index(
        "ux_billing_entitlement_bucket__tenant_external_ref",
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_entitlement_bucket__tenant_subscription_meter_period",
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_entitlement_bucket__tenant_account_meter_period",
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_external_ref"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_period_end"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_period_start"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_meter_code"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_price_id"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_subscription_id"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_account_id"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_entitlement_bucket_tenant_id"),
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    op.drop_table("billing_entitlement_bucket", schema=_SCHEMA)
