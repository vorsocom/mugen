"""make billing products and prices global catalog resources

Revision ID: 3e7c9a1b5d2f
Revises: 2d6a4f8c9b1e
Create Date: 2026-08-24 12:00:00.000000

"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence, Union
import logging

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.schema_contract import resolve_runtime_schema

# revision identifiers, used by Alembic.
revision: str = "3e7c9a1b5d2f"
down_revision: Union[str, Sequence[str], None] = "2d6a4f8c9b1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)

_REFERENCE_TABLES = (
    "billing_subscription",
    "billing_invoice_line",
    "billing_usage_event",
    "billing_entitlement_bucket",
    "ops_metering_usage_session",
    "ops_metering_usage_record",
    "ops_metering_rated_usage",
)
_BILLING_TOUCH_TABLES = (
    "billing_product",
    "billing_price",
    "billing_subscription",
    "billing_invoice_line",
    "billing_usage_event",
    "billing_entitlement_bucket",
)
_GLOBAL_PRICE_FOREIGN_KEYS = (
    (
        "billing_subscription",
        "fk_billing_subscription__price",
        "RESTRICT",
    ),
    (
        "billing_invoice_line",
        "fk_billing_invoice_line__price",
        "SET NULL",
    ),
    (
        "billing_usage_event",
        "fk_billing_usage_event__price",
        "SET NULL",
    ),
    (
        "billing_entitlement_bucket",
        "fk_billing_entitlement_bucket__price",
        "SET NULL",
    ),
)
_TENANT_PRICE_FOREIGN_KEYS = (
    (
        "billing_subscription",
        "fkx_billing_subscription__tenant_price",
        "RESTRICT",
    ),
    (
        "billing_invoice_line",
        "fkx_billing_invoice_line__tenant_price",
        "SET NULL",
    ),
    (
        "billing_usage_event",
        "fkx_billing_usage_event__tenant_price",
        "SET NULL",
    ),
    (
        "billing_entitlement_bucket",
        "fkx_billing_entitlement_bucket__tenant_price",
        "SET NULL",
    ),
)


def _qualified(table_name: str) -> str:
    return f'"{_SCHEMA}"."{table_name}"'


def _normalized_code(value: Any) -> str:
    return str(value).strip().casefold()


def _normalized_material_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().casefold()


def _stable_row_key(row: dict[str, Any]) -> tuple[Any, str]:
    return row["created_at"], str(row["id"])


def _catalog_plan(
    product_rows: list[dict[str, Any]],
    price_rows: list[dict[str, Any]],
) -> tuple[dict[Any, Any], dict[Any, Any]]:
    """Build stable legacy-to-canonical mappings or reject unsafe data."""
    attribute_violations: list[str] = []
    for resource_name, rows in (
        ("Product", product_rows),
        ("Price", price_rows),
    ):
        for row in rows:
            attributes = row.get("attributes")
            if attributes not in (None, {}):
                keys = (
                    sorted(str(key) for key in attributes)
                    if isinstance(attributes, dict)
                    else [f"<{type(attributes).__name__}>"]
                )
                attribute_violations.append(
                    f"{resource_name} {row['id']} keys={','.join(keys)}"
                )
    if attribute_violations:
        details = "; ".join(sorted(attribute_violations))
        raise RuntimeError(
            "Billing catalog migration rejected non-empty Attributes; review "
            f"tenant-specific/private metadata before retrying: {details}"
        )

    product_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in product_rows:
        normalized_code = _normalized_code(row["code"])
        if not normalized_code:
            raise RuntimeError(f"Billing Product {row['id']} has an empty Code.")
        product_groups[normalized_code].append(row)

    product_mapping: dict[Any, Any] = {}
    for normalized_code, rows in sorted(product_groups.items()):
        material_values = {
            (
                row["name"],
                row.get("description"),
                bool(row.get("deleted_at")),
            )
            for row in rows
        }
        if len(material_values) != 1:
            ids = ", ".join(sorted(str(row["id"]) for row in rows))
            raise RuntimeError(
                "Conflicting Billing Products for normalized Code "
                f"'{normalized_code}': {ids}"
            )
        canonical_id = min(rows, key=_stable_row_key)["id"]
        product_mapping.update({row["id"]: canonical_id for row in rows})

    price_groups: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
    for row in price_rows:
        normalized_code = _normalized_code(row["code"])
        if not normalized_code:
            raise RuntimeError(f"Billing Price {row['id']} has an empty Code.")
        product_id = row["product_id"]
        if product_id not in product_mapping:
            raise RuntimeError(
                f"Billing Price {row['id']} references missing Product {product_id}."
            )
        price_groups[(product_mapping[product_id], normalized_code)].append(row)

    price_mapping: dict[Any, Any] = {}
    for (product_id, normalized_code), rows in sorted(
        price_groups.items(),
        key=lambda item: (str(item[0][0]), item[0][1]),
    ):
        material_values = set()
        for row in rows:
            price_type = str(row["price_type"])
            usage_unit = _normalized_material_text(row.get("usage_unit"))
            meter_code = _normalized_material_text(row.get("meter_code"))
            if price_type == "metered" and (usage_unit is None or meter_code is None):
                raise RuntimeError(
                    f"Metered Billing Price {row['id']} requires MeterCode and UsageUnit."
                )
            if price_type != "metered" and usage_unit is None:
                meter_code = None
            if (meter_code is None) != (usage_unit is None):
                raise RuntimeError(
                    f"Billing Price {row['id']} has an incomplete meter contract."
                )
            material_values.add(
                (
                    price_type,
                    _normalized_material_text(row["currency"]),
                    row.get("unit_amount"),
                    str(row["interval_unit"]) if row.get("interval_unit") else None,
                    row.get("interval_count"),
                    row.get("trial_period_days"),
                    usage_unit,
                    meter_code,
                    bool(row.get("deleted_at")),
                )
            )
        if len(material_values) != 1:
            ids = ", ".join(sorted(str(row["id"]) for row in rows))
            raise RuntimeError(
                "Conflicting Billing Prices for global Product "
                f"{product_id} and normalized Code '{normalized_code}': {ids}"
            )
        canonical_id = min(rows, key=_stable_row_key)["id"]
        price_mapping.update({row["id"]: canonical_id for row in rows})

    return product_mapping, price_mapping


def _load_rows(table_name: str) -> list[dict[str, Any]]:
    rows = op.get_bind().execute(
        sa.text(f"SELECT * FROM {_qualified(table_name)} ORDER BY created_at, id")
    )
    return [dict(row._mapping) for row in rows]


def _disable_touch_triggers() -> None:
    for table_name in _BILLING_TOUCH_TABLES:
        op.execute(
            f"ALTER TABLE {_qualified(table_name)} DISABLE TRIGGER "
            f'"tr_touch_updated_at_row_version__{table_name}"'
        )


def _enable_touch_triggers() -> None:
    for table_name in _BILLING_TOUCH_TABLES:
        op.execute(
            f"ALTER TABLE {_qualified(table_name)} ENABLE TRIGGER "
            f'"tr_touch_updated_at_row_version__{table_name}"'
        )


def _lock_catalog_tables() -> None:
    table_list = ", ".join(
        _qualified(table_name)
        for table_name in (
            "billing_product",
            "billing_price",
            *_REFERENCE_TABLES,
        )
    )
    op.execute(f"LOCK TABLE {table_list} IN ACCESS EXCLUSIVE MODE")


def _create_legacy_mapping_tables() -> None:
    op.create_table(
        "billing_catalog_legacy_product",
        sa.Column("legacy_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_product_id", sa.Uuid(), nullable=False),
        sa.Column("row_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint(
            "legacy_id",
            name="pk_billing_catalog_legacy_product",
        ),
        schema=_SCHEMA,
    )
    op.create_table(
        "billing_catalog_legacy_price",
        sa.Column("legacy_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_product_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_price_id", sa.Uuid(), nullable=False),
        sa.Column("row_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint(
            "legacy_id",
            name="pk_billing_catalog_legacy_price",
        ),
        schema=_SCHEMA,
    )
    op.create_table(
        "billing_catalog_legacy_price_reference",
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_price_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_price_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint(
            "table_name",
            "row_id",
            name="pk_billing_catalog_legacy_price_reference",
        ),
        schema=_SCHEMA,
    )


def _backup_catalog(
    product_mapping: dict[Any, Any],
    price_mapping: dict[Any, Any],
) -> None:
    conn = op.get_bind()
    product_backup = _qualified("billing_catalog_legacy_product")
    price_backup = _qualified("billing_catalog_legacy_price")
    product_table = _qualified("billing_product")
    price_table = _qualified("billing_price")

    if product_mapping:
        conn.execute(
            sa.text(f"""
            INSERT INTO {product_backup}
                (legacy_id, tenant_id, canonical_product_id, row_data)
            SELECT id, tenant_id, :canonical_id, to_jsonb(product_row)
            FROM {product_table} AS product_row
            WHERE id = :legacy_id
            """),
            [
                {"legacy_id": legacy_id, "canonical_id": canonical_id}
                for legacy_id, canonical_id in product_mapping.items()
            ],
        )

    price_rows = _load_rows("billing_price")
    if price_rows:
        conn.execute(
            sa.text(f"""
            INSERT INTO {price_backup}
                (legacy_id, tenant_id, canonical_product_id,
                 canonical_price_id, row_data)
            SELECT id, tenant_id, :canonical_product_id,
                   :canonical_price_id, to_jsonb(price_row)
            FROM {price_table} AS price_row
            WHERE id = :legacy_id
            """),
            [
                {
                    "legacy_id": row["id"],
                    "canonical_product_id": product_mapping[row["product_id"]],
                    "canonical_price_id": price_mapping[row["id"]],
                }
                for row in price_rows
            ],
        )


def _backup_price_references() -> None:
    price_backup = _qualified("billing_catalog_legacy_price")
    reference_backup = _qualified("billing_catalog_legacy_price_reference")
    conn = op.get_bind()
    for table_name in _REFERENCE_TABLES:
        table = _qualified(table_name)
        stale_rows = conn.execute(sa.text(f"""
                SELECT reference_row.id, reference_row.price_id
                FROM {table} AS reference_row
                LEFT JOIN {price_backup} AS price_map
                  ON price_map.legacy_id = reference_row.price_id
                WHERE reference_row.price_id IS NOT NULL
                  AND price_map.legacy_id IS NULL
                ORDER BY reference_row.id
                """)).all()
        if stale_rows:
            details = ", ".join(f"{row.id}->{row.price_id}" for row in stale_rows[:20])
            raise RuntimeError(
                f"{table_name} contains unmapped Price references: {details}"
            )

        conn.execute(
            sa.text(f"""
                INSERT INTO {reference_backup}
                    (table_name, row_id, tenant_id, legacy_price_id,
                     canonical_price_id)
                SELECT :table_name, reference_row.id, reference_row.tenant_id,
                       reference_row.price_id, price_map.canonical_price_id
                FROM {table} AS reference_row
                JOIN {price_backup} AS price_map
                  ON price_map.legacy_id = reference_row.price_id
                WHERE reference_row.price_id IS NOT NULL
                """),
            {"table_name": table_name},
        )


def _drop_tenant_price_foreign_keys() -> None:
    for table_name, constraint_name, _ondelete in _TENANT_PRICE_FOREIGN_KEYS:
        op.drop_constraint(
            constraint_name,
            table_name,
            schema=_SCHEMA,
            type_="foreignkey",
        )
    op.drop_constraint(
        "fkx_billing_price__tenant_product",
        "billing_price",
        schema=_SCHEMA,
        type_="foreignkey",
    )


def _rewrite_catalog_and_references() -> None:
    product_backup = _qualified("billing_catalog_legacy_product")
    price_backup = _qualified("billing_catalog_legacy_price")
    product_table = _qualified("billing_product")
    price_table = _qualified("billing_price")

    op.execute(f"""
        UPDATE {price_table} AS price_row
        SET product_id = product_map.canonical_product_id
        FROM {product_backup} AS product_map
        WHERE price_row.product_id = product_map.legacy_id
          AND price_row.product_id <> product_map.canonical_product_id
        """)
    for table_name in _REFERENCE_TABLES:
        table = _qualified(table_name)
        op.execute(f"""
            UPDATE {table} AS reference_row
            SET price_id = price_map.canonical_price_id
            FROM {price_backup} AS price_map
            WHERE reference_row.price_id = price_map.legacy_id
              AND reference_row.price_id <> price_map.canonical_price_id
            """)

    op.alter_column(
        "billing_price",
        "meter_code",
        existing_type=postgresql.CITEXT(length=64),
        nullable=True,
        schema=_SCHEMA,
    )
    op.execute(f"""
        UPDATE {price_table}
        SET meter_code = NULL
        WHERE price_type <> 'metered'
          AND usage_unit IS NULL
        """)
    op.execute(f"""
        DELETE FROM {price_table} AS price_row
        USING {price_backup} AS price_map
        WHERE price_row.id = price_map.legacy_id
          AND price_map.legacy_id <> price_map.canonical_price_id
        """)
    op.execute(f"""
        DELETE FROM {product_table} AS product_row
        USING {product_backup} AS product_map
        WHERE product_row.id = product_map.legacy_id
          AND product_map.legacy_id <> product_map.canonical_product_id
        """)
    # Remove duplicates before trimming canonical codes. Existing tenant-scoped
    # active-only indexes may otherwise reject whitespace variants within one
    # tenant before the duplicate row can be consolidated.
    op.execute(f"UPDATE {product_table} SET code = btrim(code)")
    op.execute(f"UPDATE {price_table} SET code = btrim(code)")


def _replace_catalog_schema() -> None:
    op.drop_index(
        "ux_billing_product__tenant_code_active",
        table_name="billing_product",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_billing_product__tenant_code",
        table_name="billing_product",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_billing_product_tenant_id"),
        table_name="billing_product",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_billing_product__tenant_id_id",
        "billing_product",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_billing_product__tenant_id__admin_tenant",
        "billing_product",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("billing_product", "tenant_id", schema=_SCHEMA)

    for index_name in (
        "ux_billing_price__tenant_code_active",
        "ix_billing_price__tenant_code",
        "ix_billing_price__tenant_product",
        "ix_billing_price__tenant_meter_code",
        op.f("ix_mugen_billing_price_tenant_id"),
    ):
        op.drop_index(
            index_name,
            table_name="billing_price",
            schema=_SCHEMA,
        )
    op.drop_constraint(
        "ux_billing_price__tenant_id_id",
        "billing_price",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "fk_billing_price__tenant_id__admin_tenant",
        "billing_price",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("billing_price", "tenant_id", schema=_SCHEMA)

    op.drop_constraint(
        "ck_billing_price__meter_code_nonempty",
        "billing_price",
        schema=_SCHEMA,
        type_="check",
    )
    op.create_check_constraint(
        "ck_billing_product__code_trimmed",
        "billing_product",
        "code = btrim(code)",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__code_trimmed",
        "billing_price",
        "code = btrim(code)",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__meter_code_nonempty_if_set",
        "billing_price",
        "meter_code IS NULL OR length(btrim(meter_code)) > 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__meter_pair_complete",
        "billing_price",
        "(meter_code IS NULL) = (usage_unit IS NULL)",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__metered_pair_required",
        "billing_price",
        "price_type <> 'metered' OR "
        "(meter_code IS NOT NULL AND usage_unit IS NOT NULL)",
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_billing_product__code",
        "billing_product",
        ["code"],
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_billing_price__product_code",
        "billing_price",
        ["product_id", "code"],
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_billing_price__product_id__billing_product",
        "billing_price",
        "billing_product",
        ["product_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    for table_name, constraint_name, ondelete in _GLOBAL_PRICE_FOREIGN_KEYS:
        op.create_foreign_key(
            constraint_name,
            table_name,
            "billing_price",
            ["price_id"],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete=ondelete,
        )


def _validate_global_references() -> None:
    conn = op.get_bind()
    price_table = _qualified("billing_price")
    product_table = _qualified("billing_product")
    missing_products = conn.scalar(sa.text(f"""
            SELECT count(*)
            FROM {price_table} AS price_row
            LEFT JOIN {product_table} AS product_row
              ON product_row.id = price_row.product_id
            WHERE product_row.id IS NULL
            """))
    if missing_products:
        raise RuntimeError("Global Billing Prices contain missing Product references.")

    for table_name in _REFERENCE_TABLES:
        missing_prices = conn.scalar(sa.text(f"""
                SELECT count(*)
                FROM {_qualified(table_name)} AS reference_row
                LEFT JOIN {price_table} AS price_row
                  ON price_row.id = reference_row.price_id
                WHERE reference_row.price_id IS NOT NULL
                  AND price_row.id IS NULL
                """))
        if missing_prices:
            raise RuntimeError(
                f"{table_name} contains missing global Price references."
            )


def _reseed_acp_manifest() -> None:
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
    apply_manifest(
        op.get_bind(),
        registry.build_seed_manifest(),
        schema=_SCHEMA,
    )


def _expected_product_json(row_data: dict[str, Any]) -> dict[str, Any]:
    expected = dict(row_data)
    expected.pop("tenant_id", None)
    expected["code"] = str(expected["code"]).strip()
    return expected


def _expected_price_json(
    row_data: dict[str, Any],
    canonical_product_id: Any,
) -> dict[str, Any]:
    expected = dict(row_data)
    expected.pop("tenant_id", None)
    expected["product_id"] = str(canonical_product_id)
    expected["code"] = str(expected["code"]).strip()
    if expected["price_type"] != "metered" and expected.get("usage_unit") is None:
        expected["meter_code"] = None
    return expected


def _guard_exact_downgrade() -> None:
    conn = op.get_bind()
    product_backup = _qualified("billing_catalog_legacy_product")
    price_backup = _qualified("billing_catalog_legacy_price")
    reference_backup = _qualified("billing_catalog_legacy_price_reference")

    current_products = {
        row.id: row.row_data
        for row in conn.execute(
            sa.text(
                f"SELECT id, to_jsonb(product_row) AS row_data "
                f"FROM {_qualified('billing_product')} AS product_row"
            )
        )
    }
    canonical_products = conn.execute(sa.text(f"""
            SELECT DISTINCT ON (canonical_product_id)
                   canonical_product_id, row_data
            FROM {product_backup}
            WHERE legacy_id = canonical_product_id
            ORDER BY canonical_product_id
            """)).all()
    expected_products = {
        row.canonical_product_id: _expected_product_json(row.row_data)
        for row in canonical_products
    }
    if current_products != expected_products:
        raise RuntimeError(
            "Exact Billing catalog downgrade refused because global Products were "
            "mutated after upgrade."
        )

    current_prices = {
        row.id: row.row_data
        for row in conn.execute(
            sa.text(
                f"SELECT id, to_jsonb(price_row) AS row_data "
                f"FROM {_qualified('billing_price')} AS price_row"
            )
        )
    }
    canonical_prices = conn.execute(sa.text(f"""
            SELECT DISTINCT ON (canonical_price_id)
                   canonical_price_id, canonical_product_id, row_data
            FROM {price_backup}
            WHERE legacy_id = canonical_price_id
            ORDER BY canonical_price_id
            """)).all()
    expected_prices = {
        row.canonical_price_id: _expected_price_json(
            row.row_data,
            row.canonical_product_id,
        )
        for row in canonical_prices
    }
    if current_prices != expected_prices:
        raise RuntimeError(
            "Exact Billing catalog downgrade refused because global Prices were "
            "mutated after upgrade."
        )

    for table_name in _REFERENCE_TABLES:
        mismatch_count = conn.scalar(
            sa.text(f"""
                SELECT count(*)
                FROM (
                    SELECT reference_row.id AS row_id,
                           reference_row.price_id AS canonical_price_id
                    FROM {_qualified(table_name)} AS reference_row
                    WHERE reference_row.price_id IS NOT NULL
                ) AS current_reference
                FULL OUTER JOIN (
                    SELECT row_id, canonical_price_id
                    FROM {reference_backup}
                    WHERE table_name = :table_name
                ) AS legacy_reference
                  USING (row_id, canonical_price_id)
                WHERE current_reference.row_id IS NULL
                   OR legacy_reference.row_id IS NULL
                """),
            {"table_name": table_name},
        )
        if mismatch_count:
            raise RuntimeError(
                "Exact Billing catalog downgrade refused because Price references "
                f"in {table_name} were mutated after upgrade."
            )


def _restore_tenant_catalog_schema() -> None:
    for table_name, constraint_name, _ondelete in _GLOBAL_PRICE_FOREIGN_KEYS:
        op.drop_constraint(
            constraint_name,
            table_name,
            schema=_SCHEMA,
            type_="foreignkey",
        )
    op.drop_constraint(
        "fk_billing_price__product_id__billing_product",
        "billing_price",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_constraint(
        "ux_billing_price__product_code",
        "billing_price",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "ux_billing_product__code",
        "billing_product",
        schema=_SCHEMA,
        type_="unique",
    )
    for constraint_name, table_name in (
        ("ck_billing_price__metered_pair_required", "billing_price"),
        ("ck_billing_price__meter_pair_complete", "billing_price"),
        ("ck_billing_price__meter_code_nonempty_if_set", "billing_price"),
        ("ck_billing_price__code_trimmed", "billing_price"),
        ("ck_billing_product__code_trimmed", "billing_product"),
    ):
        op.drop_constraint(
            constraint_name,
            table_name,
            schema=_SCHEMA,
            type_="check",
        )

    op.add_column(
        "billing_product",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "billing_price",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )

    op.execute(f"DELETE FROM {_qualified('billing_price')}")
    op.execute(f"DELETE FROM {_qualified('billing_product')}")
    op.execute(f"""
        INSERT INTO {_qualified('billing_product')}
        SELECT (jsonb_populate_record(
            NULL::{_qualified('billing_product')}, row_data
        )).*
        FROM {_qualified('billing_catalog_legacy_product')}
        ORDER BY row_data->>'created_at', legacy_id
        """)
    op.execute(f"""
        INSERT INTO {_qualified('billing_price')}
        SELECT (jsonb_populate_record(
            NULL::{_qualified('billing_price')}, row_data
        )).*
        FROM {_qualified('billing_catalog_legacy_price')}
        ORDER BY row_data->>'created_at', legacy_id
        """)

    reference_backup = _qualified("billing_catalog_legacy_price_reference")
    for table_name in _REFERENCE_TABLES:
        op.execute(f"""
            UPDATE {_qualified(table_name)} AS reference_row
            SET price_id = legacy_reference.legacy_price_id
            FROM {reference_backup} AS legacy_reference
            WHERE legacy_reference.table_name = '{table_name}'
              AND legacy_reference.row_id = reference_row.id
            """)

    op.alter_column(
        "billing_product",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema=_SCHEMA,
    )
    op.alter_column(
        "billing_price",
        "tenant_id",
        existing_type=sa.Uuid(),
        nullable=False,
        schema=_SCHEMA,
    )
    op.alter_column(
        "billing_price",
        "meter_code",
        existing_type=postgresql.CITEXT(length=64),
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__meter_code_nonempty",
        "billing_price",
        "length(btrim(meter_code)) > 0",
        schema=_SCHEMA,
    )

    for table_name in ("billing_product", "billing_price"):
        op.create_foreign_key(
            f"fk_{table_name}__tenant_id__admin_tenant",
            table_name,
            "admin_tenant",
            ["tenant_id"],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="RESTRICT",
        )
        op.create_unique_constraint(
            f"ux_{table_name}__tenant_id_id",
            table_name,
            ["tenant_id", "id"],
            schema=_SCHEMA,
        )
        op.create_index(
            op.f(f"ix_mugen_{table_name}_tenant_id"),
            table_name,
            ["tenant_id"],
            unique=False,
            schema=_SCHEMA,
        )

    op.create_foreign_key(
        "fkx_billing_price__tenant_product",
        "billing_price",
        "billing_product",
        ["tenant_id", "product_id"],
        ["tenant_id", "id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    for table_name, constraint_name, ondelete in _TENANT_PRICE_FOREIGN_KEYS:
        op.create_foreign_key(
            constraint_name,
            table_name,
            "billing_price",
            ["tenant_id", "price_id"],
            ["tenant_id", "id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete=ondelete,
        )

    op.create_index(
        "ix_billing_product__tenant_code",
        "billing_product",
        ["tenant_id", "code"],
        unique=False,
        schema=_SCHEMA,
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
        "ix_billing_price__tenant_code",
        "billing_price",
        ["tenant_id", "code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_price__tenant_product",
        "billing_price",
        ["tenant_id", "product_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_billing_price__tenant_meter_code",
        "billing_price",
        ["tenant_id", "meter_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_billing_price__tenant_code_active",
        "billing_price",
        ["tenant_id", "code"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def upgrade() -> None:
    """Consolidate tenant catalogs and replace tenant-composite references."""
    if context.is_offline_mode():
        _LOG.warning(
            "Global Billing catalog consolidation requires an online transactional "
            "migration; no offline SQL is emitted for this revision."
        )
        return

    _lock_catalog_tables()
    product_rows = _load_rows("billing_product")
    price_rows = _load_rows("billing_price")
    product_mapping, price_mapping = _catalog_plan(product_rows, price_rows)

    _create_legacy_mapping_tables()
    _backup_catalog(product_mapping, price_mapping)
    _backup_price_references()
    _disable_touch_triggers()
    _drop_tenant_price_foreign_keys()
    _rewrite_catalog_and_references()
    _replace_catalog_schema()
    _validate_global_references()
    _enable_touch_triggers()
    _reseed_acp_manifest()


def downgrade() -> None:
    """Restore the exact tenant catalogs when no unsafe mutations occurred."""
    if context.is_offline_mode():
        _LOG.warning(
            "Global Billing catalog restoration requires an online transactional "
            "migration; no offline SQL is emitted for this revision."
        )
        return

    _lock_catalog_tables()
    _guard_exact_downgrade()
    _disable_touch_triggers()
    _restore_tenant_catalog_schema()
    _enable_touch_triggers()
    _validate_global_references()
    op.drop_table(
        "billing_catalog_legacy_price_reference",
        schema=_SCHEMA,
    )
    op.drop_table("billing_catalog_legacy_price", schema=_SCHEMA)
    op.drop_table("billing_catalog_legacy_product", schema=_SCHEMA)
