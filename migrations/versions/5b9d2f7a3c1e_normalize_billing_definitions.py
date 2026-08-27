"""normalize global billing definitions and tenant operations

Revision ID: 5b9d2f7a3c1e
Revises: 4a8c1e6f2b9d
Create Date: 2026-08-26 11:00:00.000000

"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence, Union
import json
import logging
import re
import uuid

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.schema_contract import resolve_runtime_schema
from mugen.core.plugin.billing.iso_4217 import (
    ISO_4217_CURRENCIES,
    ISO_4217_PUBLISHED,
    ISO_4217_SHA256,
    ISO_4217_SOURCE,
)

revision: str = "5b9d2f7a3c1e"
down_revision: Union[str, Sequence[str], None] = "4a8c1e6f2b9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)
_DEFINITION_NAMESPACE = uuid.UUID("6ee65c84-ef31-4af1-b318-69c76126f6bf")
_CURRENCY_NAMESPACE = uuid.UUID("b5bb46f0-ee96-47f9-a39d-366c251ee48e")
_ENTITLEMENT_NAMESPACE = uuid.UUID("c7245298-a6d5-4898-bf94-e8ec90109efc")
_REFERENCE_COLUMNS = (
    (
        "billing_account",
        "currency_definition_id",
        "billing_currency_definition",
        "fk_billing_account__currency_definition",
        False,
    ),
    (
        "billing_account",
        "tax_code_id",
        "billing_tax_code",
        "fk_billing_account__tax_code",
        False,
    ),
    (
        "billing_account",
        "payment_term_id",
        "billing_payment_term",
        "fk_billing_account__payment_term",
        False,
    ),
    (
        "billing_account",
        "invoice_template_id",
        "billing_invoice_template",
        "fk_billing_account__invoice_template",
        False,
    ),
    (
        "billing_account",
        "discount_definition_id",
        "billing_discount_definition",
        "fk_billing_account__discount_definition",
        False,
    ),
    (
        "billing_subscription",
        "run_definition_id",
        "billing_run_definition",
        "fk_billing_subscription__run_definition",
        True,
    ),
    (
        "billing_subscription",
        "tax_code_id",
        "billing_tax_code",
        "fk_billing_subscription__tax_code",
        False,
    ),
    (
        "billing_subscription",
        "payment_term_id",
        "billing_payment_term",
        "fk_billing_subscription__payment_term",
        False,
    ),
    (
        "billing_subscription",
        "invoice_template_id",
        "billing_invoice_template",
        "fk_billing_subscription__invoice_template",
        False,
    ),
    (
        "billing_subscription",
        "discount_definition_id",
        "billing_discount_definition",
        "fk_billing_subscription__discount_definition",
        False,
    ),
    (
        "billing_invoice",
        "currency_definition_id",
        "billing_currency_definition",
        "fk_billing_invoice__currency_definition",
        True,
    ),
    (
        "billing_invoice",
        "tax_code_id",
        "billing_tax_code",
        "fk_billing_invoice__tax_code",
        False,
    ),
    (
        "billing_invoice",
        "payment_term_id",
        "billing_payment_term",
        "fk_billing_invoice__payment_term",
        False,
    ),
    (
        "billing_invoice",
        "invoice_template_id",
        "billing_invoice_template",
        "fk_billing_invoice__invoice_template",
        False,
    ),
    (
        "billing_invoice",
        "discount_definition_id",
        "billing_discount_definition",
        "fk_billing_invoice__discount_definition",
        False,
    ),
    (
        "billing_invoice_line",
        "tax_code_id",
        "billing_tax_code",
        "fk_billing_invoice_line__tax_code",
        False,
    ),
    (
        "billing_invoice_line",
        "tax_rate_id",
        "billing_tax_rate",
        "fk_billing_invoice_line__tax_rate",
        False,
    ),
    (
        "billing_payment",
        "currency_definition_id",
        "billing_currency_definition",
        "fk_billing_payment__currency_definition",
        True,
    ),
    (
        "billing_credit_note",
        "currency_definition_id",
        "billing_currency_definition",
        "fk_billing_credit_note__currency_definition",
        True,
    ),
    (
        "billing_adjustment",
        "currency_definition_id",
        "billing_currency_definition",
        "fk_billing_adjustment__currency_definition",
        True,
    ),
    (
        "billing_ledger_entry",
        "currency_definition_id",
        "billing_currency_definition",
        "fk_billing_ledger_entry__currency_definition",
        True,
    ),
)
_CURRENCY_SNAPSHOT_TABLES = (
    "billing_price",
    "billing_invoice",
    "billing_payment",
    "billing_credit_note",
    "billing_adjustment",
    "billing_ledger_entry",
)
_TOUCH_TABLES = (
    "billing_price_entitlement",
    "billing_run_definition",
    "billing_currency_definition",
    "billing_tax_code",
    "billing_tax_rate",
    "billing_payment_term",
    "billing_invoice_template",
    "billing_discount_definition",
    "billing_entitlement_adjustment",
)


def _qualified(table_name: str) -> str:
    return f'"{_SCHEMA}"."{table_name}"'


def _base_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
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
            "row_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False
        ),
    ]


def _named_definition_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
    ]


def _install_touch_trigger(table_name: str) -> None:
    op.execute(f"""
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__{table_name}
        BEFORE UPDATE ON {_qualified(table_name)}
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version()
        """)


def _create_definition_tables() -> None:
    op.create_table(
        "billing_currency_definition",
        *_base_columns(),
        sa.Column("code", postgresql.CITEXT(length=3), nullable=False),
        sa.Column("numeric_code", sa.String(length=3), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("minor_unit", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint("length(code) = 3", name="ck_billing_currency__code_len3"),
        sa.CheckConstraint(
            "numeric_code ~ '^[0-9]{3}$'",
            name="ck_billing_currency__numeric_code",
        ),
        sa.CheckConstraint(
            "minor_unit IS NULL OR minor_unit BETWEEN 0 AND 4",
            name="ck_billing_currency__minor_unit",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_currency_definition"),
        sa.UniqueConstraint("code", name="ux_billing_currency_definition__code"),
        sa.UniqueConstraint(
            "numeric_code", name="ux_billing_currency_definition__numeric_code"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_currency_definition_is_active"),
        "billing_currency_definition",
        ["is_active"],
        schema=_SCHEMA,
    )

    op.create_table(
        "billing_run_definition",
        *_base_columns(),
        *_named_definition_columns(),
        sa.Column("frequency", postgresql.CITEXT(length=32), nullable=False),
        sa.Column(
            "interval_count",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("timezone", postgresql.CITEXT(length=128), nullable=False),
        sa.CheckConstraint(
            "frequency IN ('manual', 'daily', 'weekly', 'monthly', 'yearly')",
            name="ck_billing_run_definition__frequency",
        ),
        sa.CheckConstraint(
            "interval_count > 0", name="ck_billing_run_definition__interval_positive"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_run_definition"),
        sa.UniqueConstraint("code", name="ux_billing_run_definition__code"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_run_definition_is_active"),
        "billing_run_definition",
        ["is_active"],
        schema=_SCHEMA,
    )

    op.create_table(
        "billing_tax_code",
        *_base_columns(),
        *_named_definition_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_billing_tax_code"),
        sa.UniqueConstraint("code", name="ux_billing_tax_code__code"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_tax_code_is_active"),
        "billing_tax_code",
        ["is_active"],
        schema=_SCHEMA,
    )

    op.create_table(
        "billing_tax_rate",
        *_base_columns(),
        sa.Column("code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("tax_code_id", sa.Uuid(), nullable=False),
        sa.Column("jurisdiction_code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("rate_basis_points", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tax_code_id"],
            [f"{_SCHEMA}.billing_tax_code.id"],
            name="fk_billing_tax_rate__tax_code",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(btrim(jurisdiction_code)) > 0",
            name="ck_billing_tax_rate__jurisdiction_nonempty",
        ),
        sa.CheckConstraint(
            "rate_basis_points BETWEEN 0 AND 10000",
            name="ck_billing_tax_rate__basis_points",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_billing_tax_rate__effective_bounds",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_tax_rate"),
        sa.UniqueConstraint("code", name="ux_billing_tax_rate__code"),
        schema=_SCHEMA,
    )
    for column_name in ("tax_code_id", "effective_from", "is_active"):
        op.create_index(
            op.f(f"ix_mugen_billing_tax_rate_{column_name}"),
            "billing_tax_rate",
            [column_name],
            schema=_SCHEMA,
        )
    op.create_index(
        "ix_billing_tax_rate__tax_jurisdiction_effective",
        "billing_tax_rate",
        ["tax_code_id", "jurisdiction_code", "effective_from"],
        schema=_SCHEMA,
    )

    op.create_table(
        "billing_payment_term",
        *_base_columns(),
        *_named_definition_columns(),
        sa.Column("due_days", sa.Integer(), nullable=False),
        sa.CheckConstraint("due_days >= 0", name="ck_billing_payment_term__due_days"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_payment_term"),
        sa.UniqueConstraint("code", name="ux_billing_payment_term__code"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_payment_term_is_active"),
        "billing_payment_term",
        ["is_active"],
        schema=_SCHEMA,
    )

    op.create_table(
        "billing_invoice_template",
        *_base_columns(),
        *_named_definition_columns(),
        sa.Column("locale", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("template_format", postgresql.CITEXT(length=16), nullable=False),
        sa.Column("subject_template", sa.Text(), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "template_format IN ('html', 'text')",
            name="ck_billing_invoice_template__format",
        ),
        sa.CheckConstraint(
            "length(btrim(body_template)) > 0",
            name="ck_billing_invoice_template__body_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_invoice_template"),
        sa.UniqueConstraint("code", name="ux_billing_invoice_template__code"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_invoice_template_is_active"),
        "billing_invoice_template",
        ["is_active"],
        schema=_SCHEMA,
    )

    op.create_table(
        "billing_discount_definition",
        *_base_columns(),
        *_named_definition_columns(),
        sa.Column("kind", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("percentage_basis_points", sa.Integer(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=True),
        sa.Column("currency_definition_id", sa.Uuid(), nullable=True),
        sa.Column("coupon_code", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["currency_definition_id"],
            [f"{_SCHEMA}.billing_currency_definition.id"],
            name="fk_billing_discount_definition__currency_definition",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "kind IN ('percentage', 'fixed_amount')",
            name="ck_billing_discount_definition__kind",
        ),
        sa.CheckConstraint(
            "percentage_basis_points IS NULL OR "
            "percentage_basis_points BETWEEN 0 AND 10000",
            name="ck_billing_discount_definition__percentage",
        ),
        sa.CheckConstraint(
            "amount IS NULL OR amount >= 0",
            name="ck_billing_discount_definition__amount",
        ),
        sa.CheckConstraint(
            "(kind = 'percentage' AND percentage_basis_points IS NOT NULL "
            "AND amount IS NULL AND currency_definition_id IS NULL) OR "
            "(kind = 'fixed_amount' AND percentage_basis_points IS NULL "
            "AND amount IS NOT NULL AND currency_definition_id IS NOT NULL)",
            name="ck_billing_discount_definition__benefit_shape",
        ),
        sa.CheckConstraint(
            "coupon_code IS NULL OR length(btrim(coupon_code)) > 0",
            name="ck_billing_discount_definition__coupon_nonempty",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from",
            name="ck_billing_discount_definition__valid_bounds",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_discount_definition"),
        sa.UniqueConstraint("code", name="ux_billing_discount_definition__code"),
        sa.UniqueConstraint(
            "coupon_code", name="ux_billing_discount_definition__coupon_code"
        ),
        schema=_SCHEMA,
    )
    for column_name in ("currency_definition_id", "is_active"):
        op.create_index(
            op.f(f"ix_mugen_billing_discount_definition_{column_name}"),
            "billing_discount_definition",
            [column_name],
            schema=_SCHEMA,
        )

    op.create_table(
        "billing_price_entitlement",
        *_base_columns(),
        sa.Column("price_id", sa.Uuid(), nullable=False),
        sa.Column("meter_definition_id", sa.Uuid(), nullable=False),
        sa.Column("included_quantity", sa.BigInteger(), nullable=False),
        sa.Column(
            "rollover_policy",
            postgresql.CITEXT(length=32),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["price_id"],
            [f"{_SCHEMA}.billing_price.id"],
            name="fk_billing_price_entitlement__price",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["meter_definition_id"],
            [f"{_SCHEMA}.billing_meter_definition.id"],
            name="fk_billing_price_entitlement__meter_definition",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            name="fk_billing_price_entitlement__deleted_by_user_id__admin_user",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "included_quantity >= 0",
            name="ck_billing_price_entitlement__included_nonnegative",
        ),
        sa.CheckConstraint(
            "rollover_policy = 'none'",
            name="ck_billing_price_entitlement__rollover_policy",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_billing_price_entitlement__archive_actor",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_price_entitlement"),
        schema=_SCHEMA,
    )
    for column_name in ("price_id", "meter_definition_id", "deleted_at"):
        op.create_index(
            op.f(f"ix_mugen_billing_price_entitlement_{column_name}"),
            "billing_price_entitlement",
            [column_name],
            schema=_SCHEMA,
        )
    op.create_index(
        "ux_billing_price_entitlement__active_price_meter",
        "billing_price_entitlement",
        ["price_id", "meter_definition_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def _create_legacy_state_table() -> None:
    op.create_table(
        "billing_definition_legacy_state",
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("state_kind", sa.String(length=64), nullable=False),
        sa.Column("row_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint(
            "table_name",
            "row_id",
            "state_kind",
            name="pk_billing_definition_legacy_state",
        ),
        schema=_SCHEMA,
    )


def _seed_currencies() -> None:
    conn = op.get_bind()
    payloads = [
        {
            "id": uuid.uuid5(_CURRENCY_NAMESPACE, code),
            "code": code,
            "numeric_code": numeric_code,
            "display_name": display_name,
            "minor_unit": minor_unit,
            "attributes": json.dumps(
                {
                    "iso_4217_published": ISO_4217_PUBLISHED,
                    "source": ISO_4217_SOURCE,
                    "source_sha256": ISO_4217_SHA256,
                },
                sort_keys=True,
            ),
        }
        for code, numeric_code, minor_unit, display_name in ISO_4217_CURRENCIES
    ]
    conn.execute(
        sa.text(f"""
            INSERT INTO {_qualified('billing_currency_definition')}
                (id, code, numeric_code, display_name, minor_unit, is_active,
                 attributes)
            VALUES
                (:id, :code, :numeric_code, :display_name, :minor_unit, false,
                 CAST(:attributes AS jsonb))
        """),
        payloads,
    )
    known_codes = {row[0] for row in ISO_4217_CURRENCIES}
    used_codes: set[str] = set()
    for table_name in _CURRENCY_SNAPSHOT_TABLES:
        values = conn.execute(
            sa.text(
                f"SELECT DISTINCT upper(btrim(currency)) FROM {_qualified(table_name)}"
            )
        ).scalars()
        used_codes.update(str(value) for value in values if value is not None)
    unknown = sorted(used_codes - known_codes)
    if unknown:
        raise RuntimeError(
            "Billing currency snapshots are absent from pinned ISO 4217 data: "
            + ", ".join(unknown)
        )
    if used_codes:
        conn.execute(
            sa.text(f"""
                UPDATE {_qualified('billing_currency_definition')}
                SET is_active = true
                WHERE code IN :codes
            """).bindparams(sa.bindparam("codes", expanding=True)),
            {"codes": sorted(used_codes)},
        )


def _normalize_code(value: Any) -> str:
    return str(value).strip().casefold()


def _safe_code(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", _normalize_code(value)).strip("-")
    return normalized or "legacy"


def _entitlement_plan(
    price_rows: list[dict[str, Any]],
    meter_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate validated included_usage metadata into structured rules."""
    meters = {_normalize_code(row["code"]): row for row in meter_rows}
    aliases = {
        "cim": "valet.customer-inbox.minutes",
        "cct": "valet.customer-inbox.tasks",
        "minutes": "valet.customer-inbox.minutes",
        "tasks": "valet.customer-inbox.tasks",
    }
    rules: list[dict[str, Any]] = []
    for price in price_rows:
        attributes = price.get("attributes")
        if not isinstance(attributes, dict) or "included_usage" not in attributes:
            continue
        included = attributes["included_usage"]
        if not isinstance(included, dict):
            raise RuntimeError(
                f"Price {price['id']} included_usage must be an object mapping meters "
                "to non-negative whole quantities."
            )
        if (
            str(price.get("price_type")) != "recurring"
            or not price.get("interval_unit")
            or not price.get("interval_count")
        ):
            raise RuntimeError(
                f"Price {price['id']} has entitlements but is not a complete "
                "recurring Price."
            )
        if price.get("deleted_at") is not None:
            raise RuntimeError(f"Price {price['id']} has entitlements but is archived.")
        seen: set[uuid.UUID] = set()
        for raw_meter_code, raw_quantity in sorted(included.items()):
            code = aliases.get(
                _normalize_code(raw_meter_code), _normalize_code(raw_meter_code)
            )
            meter = meters.get(code)
            if meter is None or not meter.get("is_active"):
                raise RuntimeError(
                    f"Price {price['id']} entitlement references absent or inactive "
                    f"meter Code '{code}'."
                )
            if isinstance(raw_quantity, bool) or not isinstance(raw_quantity, int):
                raise RuntimeError(
                    f"Price {price['id']} entitlement for '{code}' must be a "
                    "whole number."
                )
            if raw_quantity < 0:
                raise RuntimeError(
                    f"Price {price['id']} entitlement for '{code}' must be "
                    "non-negative."
                )
            meter_id = meter["id"]
            if meter_id in seen:
                raise RuntimeError(
                    f"Price {price['id']} includes duplicate aliases for meter "
                    f"'{code}'."
                )
            seen.add(meter_id)
            rule_id = uuid.uuid5(
                _ENTITLEMENT_NAMESPACE,
                f"{price['id']}:{meter_id}",
            )
            rules.append(
                {
                    "id": rule_id,
                    "price_id": price["id"],
                    "meter_definition_id": meter_id,
                    "included_quantity": raw_quantity,
                    "rollover_policy": "none",
                    "attributes": {
                        "migration_source": "Price.Attributes.included_usage"
                    },
                    "remaining_attributes": {
                        key: value
                        for key, value in attributes.items()
                        if key != "included_usage"
                    },
                }
            )
    return rules


def _add_reference_columns() -> None:
    op.add_column(
        "billing_price",
        sa.Column("currency_definition_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_billing_price__currency_definition",
        "billing_price",
        "billing_currency_definition",
        ["currency_definition_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_mugen_billing_price_currency_definition_id"),
        "billing_price",
        ["currency_definition_id"],
        schema=_SCHEMA,
    )
    for table_name, column_name, target, foreign_key, indexed in _REFERENCE_COLUMNS:
        op.add_column(
            table_name,
            sa.Column(column_name, sa.Uuid(), nullable=True),
            schema=_SCHEMA,
        )
        op.create_foreign_key(
            foreign_key,
            table_name,
            target,
            [column_name],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="RESTRICT",
        )
        if indexed:
            op.create_index(
                op.f(f"ix_mugen_{table_name}_{column_name}"),
                table_name,
                [column_name],
                schema=_SCHEMA,
            )


def _backfill_currency_references() -> None:
    for table_name in _CURRENCY_SNAPSHOT_TABLES:
        op.execute(f"""
            UPDATE {_qualified(table_name)} AS financial
            SET currency_definition_id = currency.id,
                currency = upper(currency.code)
            FROM {_qualified('billing_currency_definition')} AS currency
            WHERE upper(btrim(financial.currency)) = upper(currency.code)
        """)
        missing = op.get_bind().execute(sa.text(f"""
                SELECT id, currency
                FROM {_qualified(table_name)}
                WHERE currency_definition_id IS NULL
                ORDER BY id
                LIMIT 20
            """)).all()
        if missing:
            raise RuntimeError(
                f"{table_name} contains currency snapshots that could not be "
                "backfilled: " + ", ".join(f"{row[0]}={row[1]}" for row in missing)
            )
        op.alter_column(
            table_name,
            "currency_definition_id",
            existing_type=sa.Uuid(),
            nullable=False,
            schema=_SCHEMA,
        )


def _migrate_billing_runs() -> None:
    conn = op.get_bind()
    run_types = [
        str(value)
        for value in conn.execute(
            sa.text(
                f"SELECT DISTINCT run_type FROM {_qualified('billing_run')} "
                "ORDER BY run_type"
            )
        ).scalars()
    ]
    grouped_run_types: dict[str, list[str]] = defaultdict(list)
    for run_type in run_types:
        grouped_run_types[_safe_code(run_type)].append(run_type)
    definitions = []
    for code, legacy_values in sorted(grouped_run_types.items()):
        run_type = sorted(legacy_values, key=lambda value: (len(value), value))[0]
        frequency = (
            code if code in {"daily", "weekly", "monthly", "yearly"} else "manual"
        )
        definitions.append(
            {
                "id": uuid.uuid5(_DEFINITION_NAMESPACE, f"billing-run:{code}"),
                "code": code,
                "display_name": str(run_type).strip(),
                "description": "Migrated from legacy BillingRun.RunType.",
                "frequency": frequency,
                "interval_count": 1,
                "timezone": "UTC",
                "attributes": json.dumps(
                    {
                        "migration_source": "BillingRun.RunType",
                        "legacy_value": run_type,
                    },
                    sort_keys=True,
                ),
                "legacy_values": legacy_values,
                "legacy_value": run_type,
            }
        )
    if definitions:
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_run_definition')}
                    (id, code, display_name, description, frequency, interval_count,
                     timezone, is_active, attributes)
                VALUES
                    (:id, :code, :display_name, :description, :frequency,
                     :interval_count, :timezone, true, CAST(:attributes AS jsonb))
            """),
            definitions,
        )
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_definition_legacy_state')}
                    (table_name, row_id, state_kind, row_data)
                VALUES
                    ('billing_run_definition', :id, 'migrated_definition',
                     jsonb_build_object('run_type', :legacy_value))
            """),
            definitions,
        )
    op.execute(f"""
        INSERT INTO {_qualified('billing_definition_legacy_state')}
            (table_name, row_id, state_kind, row_data)
        SELECT 'billing_run', id, 'legacy_row', to_jsonb(run_row)
        FROM {_qualified('billing_run')} AS run_row
    """)

    op.add_column(
        "billing_run",
        sa.Column("definition_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column("retry_of_run_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column(
            "attempt_number", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column("failure_code", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column("failure_detail", sa.Text(), nullable=True),
        schema=_SCHEMA,
    )
    for definition in definitions:
        for legacy_value in definition["legacy_values"]:
            conn.execute(
                sa.text(f"""
                    UPDATE {_qualified('billing_run')}
                    SET definition_id = :definition_id
                    WHERE run_type = :legacy_value
                """),
                {
                    "definition_id": definition["id"],
                    "legacy_value": legacy_value,
                },
            )
    op.execute(f"""
        UPDATE {_qualified('billing_run')}
        SET completed_at = finished_at,
            failure_detail = error_message,
            failure_code = CASE
                WHEN error_message IS NULL THEN NULL
                ELSE 'legacy_error'
            END
    """)
    missing = (
        conn.execute(
            sa.text(
                f"SELECT id FROM {_qualified('billing_run')} "
                "WHERE definition_id IS NULL LIMIT 20"
            )
        )
        .scalars()
        .all()
    )
    if missing:
        raise RuntimeError(
            "Billing Runs could not resolve a migrated definition: "
            + ", ".join(str(value) for value in missing)
        )
    op.alter_column(
        "billing_run",
        "definition_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_run__tenant_run_type_period",
        table_name="billing_run",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_run_run_type"),
        table_name="billing_run",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_billing_run__run_type_nonempty",
        "billing_run",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column("billing_run", "run_type", schema=_SCHEMA)
    op.drop_column("billing_run", "finished_at", schema=_SCHEMA)
    op.drop_column("billing_run", "error_message", schema=_SCHEMA)
    op.create_foreign_key(
        "fk_billing_run__definition",
        "billing_run",
        "billing_run_definition",
        ["definition_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fkx_billing_run__tenant_retry_of_run",
        "billing_run",
        "billing_run",
        ["tenant_id", "retry_of_run_id"],
        ["tenant_id", "id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_billing_run__attempt_positive",
        "billing_run",
        "attempt_number > 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_run__failure_code_nonempty_if_set",
        "billing_run",
        "failure_code IS NULL OR length(btrim(failure_code)) > 0",
        schema=_SCHEMA,
    )
    for column_name in ("definition_id", "retry_of_run_id"):
        op.create_index(
            op.f(f"ix_mugen_billing_run_{column_name}"),
            "billing_run",
            [column_name],
            schema=_SCHEMA,
        )
    op.create_index(
        "ix_billing_run__tenant_definition_period",
        "billing_run",
        ["tenant_id", "definition_id", "period_start"],
        schema=_SCHEMA,
    )


def _migrate_price_entitlements() -> None:
    conn = op.get_bind()
    price_rows = [
        dict(row._mapping)
        for row in conn.execute(
            sa.text(f"SELECT * FROM {_qualified('billing_price')} ORDER BY id")
        )
    ]
    meter_rows = [
        dict(row._mapping)
        for row in conn.execute(
            sa.text(
                f"SELECT * FROM {_qualified('billing_meter_definition')} ORDER BY id"
            )
        )
    ]
    rules = _entitlement_plan(price_rows, meter_rows)
    if rules:
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_price_entitlement')}
                    (id, price_id, meter_definition_id, included_quantity,
                     rollover_policy, attributes)
                VALUES
                    (:id, :price_id, :meter_definition_id, :included_quantity,
                     :rollover_policy, CAST(:attributes AS jsonb))
            """),
            [
                {
                    **rule,
                    "attributes": json.dumps(rule["attributes"], sort_keys=True),
                }
                for rule in rules
            ],
        )
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_definition_legacy_state')}
                    (table_name, row_id, state_kind, row_data)
                VALUES
                    ('billing_price_entitlement', :id, 'migrated_entitlement',
                     jsonb_build_object('price_id', CAST(:price_id AS text)))
            """),
            rules,
        )
    for price in price_rows:
        attributes = price.get("attributes")
        if not isinstance(attributes, dict) or "included_usage" not in attributes:
            continue
        remaining = {
            key: value for key, value in attributes.items() if key != "included_usage"
        }
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_definition_legacy_state')}
                    (table_name, row_id, state_kind, row_data)
                VALUES
                    ('billing_price', :id, 'included_usage',
                     jsonb_build_object('attributes', CAST(:attributes AS jsonb)))
            """),
            {"id": price["id"], "attributes": json.dumps(attributes, sort_keys=True)},
        )
        conn.execute(
            sa.text(f"""
                UPDATE {_qualified('billing_price')}
                SET attributes = CAST(:attributes AS jsonb)
                WHERE id = :id
            """),
            {
                "id": price["id"],
                "attributes": (
                    json.dumps(remaining, sort_keys=True) if remaining else None
                ),
            },
        )


def _extend_entitlement_buckets() -> None:
    op.add_column(
        "billing_entitlement_bucket",
        sa.Column("price_entitlement_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_entitlement_bucket",
        sa.Column("billing_run_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_entitlement_bucket",
        sa.Column(
            "adjustment_quantity",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_entitlement_bucket",
        sa.Column(
            "generation_source",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'legacy'"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_billing_entitlement_bucket__price_entitlement",
        "billing_entitlement_bucket",
        "billing_price_entitlement",
        ["price_entitlement_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fkx_billing_entitlement_bucket__tenant_billing_run",
        "billing_entitlement_bucket",
        "billing_run",
        ["tenant_id", "billing_run_id"],
        ["tenant_id", "id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )
    for column_name in ("price_entitlement_id", "billing_run_id"):
        op.create_index(
            op.f(f"ix_mugen_billing_entitlement_bucket_{column_name}"),
            "billing_entitlement_bucket",
            [column_name],
            schema=_SCHEMA,
        )
    op.drop_constraint(
        "ck_billing_entitlement_bucket__consumed_within_capacity",
        "billing_entitlement_bucket",
        schema=_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_billing_entitlement_bucket__consumed_within_capacity",
        "billing_entitlement_bucket",
        "consumed_quantity <= "
        "(included_quantity + rollover_quantity + adjustment_quantity)",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_entitlement_bucket__capacity_nonnegative",
        "billing_entitlement_bucket",
        "included_quantity + rollover_quantity + adjustment_quantity >= 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_entitlement_bucket__generation_source",
        "billing_entitlement_bucket",
        "generation_source IN "
        "('legacy', 'subscription_activation', 'period_advance', "
        "'billing_run', 'reconciliation')",
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_billing_entitlement_bucket__generated_period",
        "billing_entitlement_bucket",
        [
            "tenant_id",
            "account_id",
            "subscription_id",
            "price_entitlement_id",
            "period_start",
            "period_end",
        ],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text(
            "subscription_id IS NOT NULL AND price_entitlement_id IS NOT NULL"
        ),
    )


def _create_entitlement_adjustment_table() -> None:
    op.create_table(
        "billing_entitlement_adjustment",
        *_base_columns(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("bucket_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("quantity_delta", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_before", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_after", sa.BigInteger(), nullable=False),
        sa.Column("capacity_after", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            name="fk_billing_entitlement_adjustment__tenant_id__admin_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            name="fk_billing_entitlement_adjustment__actor_user",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "bucket_id"],
            [
                f"{_SCHEMA}.billing_entitlement_bucket.tenant_id",
                f"{_SCHEMA}.billing_entitlement_bucket.id",
            ],
            name="fkx_billing_entitlement_adjustment__tenant_bucket",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "account_id"],
            [
                f"{_SCHEMA}.billing_account.tenant_id",
                f"{_SCHEMA}.billing_account.id",
            ],
            name="fkx_billing_entitlement_adjustment__tenant_account",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subscription_id"],
            [
                f"{_SCHEMA}.billing_subscription.tenant_id",
                f"{_SCHEMA}.billing_subscription.id",
            ],
            name="fkx_billing_entitlement_adjustment__tenant_subscription",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0",
            name="ck_billing_entitlement_adjustment__delta_nonzero",
        ),
        sa.CheckConstraint(
            "adjustment_after = adjustment_before + quantity_delta",
            name="ck_billing_entitlement_adjustment__adjustment_math",
        ),
        sa.CheckConstraint(
            "capacity_after >= 0",
            name="ck_billing_entitlement_adjustment__capacity_nonnegative",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0",
            name="ck_billing_entitlement_adjustment__reason_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_entitlement_adjustment"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="ux_billing_entitlement_adjustment__tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="ux_billing_entitlement_adjustment__tenant_idempotency",
        ),
        schema=_SCHEMA,
    )
    for column_name in ("tenant_id", "bucket_id", "account_id", "subscription_id"):
        op.create_index(
            op.f(f"ix_mugen_billing_entitlement_adjustment_{column_name}"),
            "billing_entitlement_adjustment",
            [column_name],
            schema=_SCHEMA,
        )
    op.create_index(
        "ix_billing_entitlement_adjustment__tenant_bucket_occurred",
        "billing_entitlement_adjustment",
        ["tenant_id", "bucket_id", "occurred_at"],
        schema=_SCHEMA,
    )


def _reseed_acp() -> None:
    mugen_cfg = context.config.attributes.get("mugen_cfg")
    if not mugen_cfg:
        raise RuntimeError("mugen_cfg was not provided to Alembic env.")
    if not bool(mugen_cfg.get("acp", {}).get("seed_acp", False)):
        _LOG.warning("ACP reseed skipped by config.")
        return
    from mugen.core.plugin.acp.migration.apply_manifest import apply_manifest
    from mugen.core.plugin.acp.migration.loader import contribute_all
    from mugen.core.plugin.acp.sdk.registry import AdminRegistry

    registry = AdminRegistry(strict_permission_decls=True)
    contribute_all(registry, mugen_cfg=mugen_cfg)
    apply_manifest(op.get_bind(), registry.build_seed_manifest(), schema=_SCHEMA)


def upgrade() -> None:
    """Install global policy definitions and tenant execution provenance."""
    if context.is_offline_mode():
        _LOG.warning("Skipping data-dependent billing definition cutover offline.")
        return
    lock_tables = (
        "billing_price",
        "billing_account",
        "billing_subscription",
        "billing_run",
        "billing_invoice",
        "billing_invoice_line",
        "billing_payment",
        "billing_credit_note",
        "billing_adjustment",
        "billing_ledger_entry",
        "billing_entitlement_bucket",
    )
    op.execute(
        "LOCK TABLE "
        + ", ".join(_qualified(table_name) for table_name in lock_tables)
        + " IN ACCESS EXCLUSIVE MODE"
    )
    invalid_periods = op.get_bind().execute(sa.text(f"""
            SELECT id
            FROM {_qualified('billing_subscription')}
            WHERE (current_period_start IS NULL) <> (current_period_end IS NULL)
               OR current_period_end <= current_period_start
            ORDER BY id
            LIMIT 20
        """)).scalars().all()
    if invalid_periods:
        raise RuntimeError(
            "Subscriptions contain invalid current-period pairs: "
            + ", ".join(str(value) for value in invalid_periods)
        )

    _create_definition_tables()
    _create_legacy_state_table()
    _seed_currencies()
    _add_reference_columns()
    _backfill_currency_references()
    _migrate_billing_runs()

    op.add_column(
        "billing_invoice",
        sa.Column("billing_run_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fkx_billing_invoice__tenant_billing_run",
        "billing_invoice",
        "billing_run",
        ["tenant_id", "billing_run_id"],
        ["tenant_id", "id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_billing_subscription__period_pair",
        "billing_subscription",
        "(current_period_start IS NULL) = (current_period_end IS NULL)",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_subscription__period_bounds",
        "billing_subscription",
        "current_period_end IS NULL OR current_period_end > current_period_start",
        schema=_SCHEMA,
    )

    _migrate_price_entitlements()
    _extend_entitlement_buckets()
    _create_entitlement_adjustment_table()
    for table_name in _TOUCH_TABLES:
        _install_touch_trigger(table_name)
    _reseed_acp()


def _scalar_count(statement: str, parameters: dict[str, Any] | None = None) -> int:
    return int(op.get_bind().execute(sa.text(statement), parameters or {}).scalar_one())


def _assert_downgrade_safe() -> None:
    for table_name in (
        "billing_tax_code",
        "billing_tax_rate",
        "billing_payment_term",
        "billing_invoice_template",
        "billing_discount_definition",
        "billing_entitlement_adjustment",
    ):
        if _scalar_count(f"SELECT count(*) FROM {_qualified(table_name)}"):
            raise RuntimeError(
                f"Cannot downgrade: {table_name} contains post-cutover definitions "
                "or operational records."
            )

    reference_guards = {
        "billing_account": (
            "currency_definition_id",
            "tax_code_id",
            "payment_term_id",
            "invoice_template_id",
            "discount_definition_id",
        ),
        "billing_subscription": (
            "run_definition_id",
            "tax_code_id",
            "payment_term_id",
            "invoice_template_id",
            "discount_definition_id",
        ),
        "billing_invoice": (
            "billing_run_id",
            "tax_code_id",
            "payment_term_id",
            "invoice_template_id",
            "discount_definition_id",
        ),
        "billing_invoice_line": ("tax_code_id", "tax_rate_id"),
    }
    for table_name, columns in reference_guards.items():
        predicate = " OR ".join(f"{column} IS NOT NULL" for column in columns)
        if _scalar_count(
            f"SELECT count(*) FROM {_qualified(table_name)} WHERE {predicate}"
        ):
            raise RuntimeError(
                f"Cannot downgrade: {table_name} uses new global references."
            )

    if _scalar_count(f"""
        SELECT count(*)
        FROM {_qualified('billing_entitlement_bucket')}
        WHERE price_entitlement_id IS NOT NULL
           OR billing_run_id IS NOT NULL
           OR adjustment_quantity <> 0
           OR generation_source <> 'legacy'
    """):
        raise RuntimeError(
            "Cannot downgrade: entitlement buckets contain generated provenance "
            "or adjustments."
        )

    if _scalar_count(f"""
        SELECT count(*)
        FROM {_qualified('billing_run')} AS run
        LEFT JOIN {_qualified('billing_definition_legacy_state')} AS legacy
          ON legacy.table_name = 'billing_run'
         AND legacy.row_id = run.id
         AND legacy.state_kind = 'legacy_row'
        WHERE legacy.row_id IS NULL
    """):
        raise RuntimeError("Cannot downgrade: Billing Runs contain new executions.")
    if _scalar_count(f"""
        SELECT count(*)
        FROM {_qualified('billing_run_definition')} AS definition
        LEFT JOIN {_qualified('billing_definition_legacy_state')} AS legacy
          ON legacy.table_name = 'billing_run_definition'
         AND legacy.row_id = definition.id
         AND legacy.state_kind = 'migrated_definition'
        WHERE legacy.row_id IS NULL
    """):
        raise RuntimeError("Cannot downgrade: new Billing Run Definitions exist.")
    if _scalar_count(f"""
        SELECT count(*)
        FROM {_qualified('billing_price_entitlement')} AS entitlement
        LEFT JOIN {_qualified('billing_definition_legacy_state')} AS legacy
          ON legacy.table_name = 'billing_price_entitlement'
         AND legacy.row_id = entitlement.id
         AND legacy.state_kind = 'migrated_entitlement'
        WHERE legacy.row_id IS NULL
    """):
        raise RuntimeError("Cannot downgrade: new Price Entitlement rules exist.")

    if _scalar_count(f"""
        SELECT count(*)
        FROM {_qualified('billing_currency_definition')} AS currency
        WHERE currency.is_active
          AND NOT EXISTS (
              SELECT 1 FROM {_qualified('billing_price')} p
              WHERE upper(p.currency) = upper(currency.code)
              UNION ALL
              SELECT 1 FROM {_qualified('billing_invoice')} i
              WHERE upper(i.currency) = upper(currency.code)
              UNION ALL
              SELECT 1 FROM {_qualified('billing_payment')} p
              WHERE upper(p.currency) = upper(currency.code)
              UNION ALL
              SELECT 1 FROM {_qualified('billing_credit_note')} c
              WHERE upper(c.currency) = upper(currency.code)
              UNION ALL
              SELECT 1 FROM {_qualified('billing_adjustment')} a
              WHERE upper(a.currency) = upper(currency.code)
              UNION ALL
              SELECT 1 FROM {_qualified('billing_ledger_entry')} l
              WHERE upper(l.currency) = upper(currency.code)
          )
    """):
        raise RuntimeError(
            "Cannot downgrade: unused ISO currencies were activated after cutover."
        )


def _restore_legacy_price_attributes() -> None:
    op.execute(f"""
        UPDATE {_qualified('billing_price')} AS price
        SET attributes = legacy.row_data -> 'attributes'
        FROM {_qualified('billing_definition_legacy_state')} AS legacy
        WHERE legacy.table_name = 'billing_price'
          AND legacy.state_kind = 'included_usage'
          AND legacy.row_id = price.id
    """)


def _restore_legacy_billing_runs() -> None:
    op.drop_index(
        "ix_billing_run__tenant_definition_period",
        table_name="billing_run",
        schema=_SCHEMA,
    )
    for column_name in ("retry_of_run_id", "definition_id"):
        op.drop_index(
            op.f(f"ix_mugen_billing_run_{column_name}"),
            table_name="billing_run",
            schema=_SCHEMA,
        )
    op.drop_constraint(
        "fkx_billing_run__tenant_retry_of_run",
        "billing_run",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_billing_run__definition",
        "billing_run",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    for constraint_name in (
        "ck_billing_run__failure_code_nonempty_if_set",
        "ck_billing_run__attempt_positive",
    ):
        op.drop_constraint(
            constraint_name,
            "billing_run",
            schema=_SCHEMA,
            type_="check",
        )
    op.add_column(
        "billing_run",
        sa.Column("run_type", postgresql.CITEXT(length=64), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_run",
        sa.Column("error_message", sa.Text(), nullable=True),
        schema=_SCHEMA,
    )
    op.execute(f"""
        UPDATE {_qualified('billing_run')} AS run
        SET run_type = legacy.row_data ->> 'run_type',
            finished_at = (legacy.row_data ->> 'finished_at')::timestamptz,
            error_message = legacy.row_data ->> 'error_message'
        FROM {_qualified('billing_definition_legacy_state')} AS legacy
        WHERE legacy.table_name = 'billing_run'
          AND legacy.state_kind = 'legacy_row'
          AND legacy.row_id = run.id
    """)
    op.alter_column(
        "billing_run",
        "run_type",
        existing_type=postgresql.CITEXT(length=64),
        nullable=False,
        schema=_SCHEMA,
    )
    for column_name in (
        "failure_detail",
        "failure_code",
        "completed_at",
        "attempt_number",
        "retry_of_run_id",
        "definition_id",
    ):
        op.drop_column("billing_run", column_name, schema=_SCHEMA)
    op.create_check_constraint(
        "ck_billing_run__run_type_nonempty",
        "billing_run",
        "length(btrim(run_type)) > 0",
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_run_run_type"),
        "billing_run",
        ["run_type"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_run__tenant_run_type_period",
        "billing_run",
        ["tenant_id", "run_type", "period_start"],
        schema=_SCHEMA,
    )


def _shrink_entitlement_buckets() -> None:
    op.drop_index(
        "ux_billing_entitlement_bucket__generated_period",
        table_name="billing_entitlement_bucket",
        schema=_SCHEMA,
    )
    for column_name in ("billing_run_id", "price_entitlement_id"):
        op.drop_index(
            op.f(f"ix_mugen_billing_entitlement_bucket_{column_name}"),
            table_name="billing_entitlement_bucket",
            schema=_SCHEMA,
        )
    op.drop_constraint(
        "fkx_billing_entitlement_bucket__tenant_billing_run",
        "billing_entitlement_bucket",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_billing_entitlement_bucket__price_entitlement",
        "billing_entitlement_bucket",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    for constraint_name in (
        "ck_billing_entitlement_bucket__generation_source",
        "ck_billing_entitlement_bucket__capacity_nonnegative",
        "ck_billing_entitlement_bucket__consumed_within_capacity",
    ):
        op.drop_constraint(
            constraint_name,
            "billing_entitlement_bucket",
            schema=_SCHEMA,
            type_="check",
        )
    op.create_check_constraint(
        "ck_billing_entitlement_bucket__consumed_within_capacity",
        "billing_entitlement_bucket",
        "consumed_quantity <= (included_quantity + rollover_quantity)",
        schema=_SCHEMA,
    )
    for column_name in (
        "generation_source",
        "adjustment_quantity",
        "billing_run_id",
        "price_entitlement_id",
    ):
        op.drop_column("billing_entitlement_bucket", column_name, schema=_SCHEMA)


def _drop_reference_columns() -> None:
    for table_name, column_name, _target, foreign_key, indexed in reversed(
        _REFERENCE_COLUMNS
    ):
        if indexed:
            op.drop_index(
                op.f(f"ix_mugen_{table_name}_{column_name}"),
                table_name=table_name,
                schema=_SCHEMA,
            )
        op.drop_constraint(
            foreign_key,
            table_name,
            schema=_SCHEMA,
            type_="foreignkey",
        )
        op.drop_column(table_name, column_name, schema=_SCHEMA)
    op.drop_index(
        op.f("ix_mugen_billing_price_currency_definition_id"),
        table_name="billing_price",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "fk_billing_price__currency_definition",
        "billing_price",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("billing_price", "currency_definition_id", schema=_SCHEMA)


def downgrade() -> None:
    """Restore the legacy model only before new definition-backed state is used."""
    if context.is_offline_mode():
        _LOG.warning("Skipping data-dependent billing definition downgrade offline.")
        return
    _assert_downgrade_safe()
    _restore_legacy_price_attributes()
    op.execute(
        f"DROP TRIGGER IF EXISTS "
        "tr_touch_updated_at_row_version__billing_entitlement_adjustment "
        f"ON {_qualified('billing_entitlement_adjustment')}"
    )
    op.drop_table("billing_entitlement_adjustment", schema=_SCHEMA)
    _shrink_entitlement_buckets()

    op.drop_constraint(
        "fkx_billing_invoice__tenant_billing_run",
        "billing_invoice",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("billing_invoice", "billing_run_id", schema=_SCHEMA)
    for constraint_name in (
        "ck_billing_subscription__period_bounds",
        "ck_billing_subscription__period_pair",
    ):
        op.drop_constraint(
            constraint_name,
            "billing_subscription",
            schema=_SCHEMA,
            type_="check",
        )
    _restore_legacy_billing_runs()
    _drop_reference_columns()

    for table_name in reversed(_TOUCH_TABLES[:-1]):
        op.execute(
            f"DROP TRIGGER IF EXISTS tr_touch_updated_at_row_version__{table_name} "
            f"ON {_qualified(table_name)}"
        )
    for table_name in (
        "billing_price_entitlement",
        "billing_discount_definition",
        "billing_invoice_template",
        "billing_payment_term",
        "billing_tax_rate",
        "billing_tax_code",
        "billing_run_definition",
        "billing_currency_definition",
    ):
        op.drop_table(table_name, schema=_SCHEMA)
    op.drop_table("billing_definition_legacy_state", schema=_SCHEMA)
