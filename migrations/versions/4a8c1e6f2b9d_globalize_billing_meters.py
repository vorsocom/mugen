"""globalize canonical billing meter definitions

Revision ID: 4a8c1e6f2b9d
Revises: 3e7c9a1b5d2f
Create Date: 2026-08-26 10:00:00.000000

"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Sequence, Union
import logging

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.schema_contract import resolve_runtime_schema

revision: str = "4a8c1e6f2b9d"
down_revision: Union[str, Sequence[str], None] = "3e7c9a1b5d2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)
_METER_REFERENCE_TABLES = (
    (
        "ops_metering_meter_policy",
        "fkx_ops_metering_meter_policy__tenant_meter_definition",
        "fk_ops_metering_meter_policy__meter_definition",
        "CASCADE",
    ),
    (
        "ops_metering_usage_session",
        "fkx_ops_metering_usage_session__tenant_meter_definition",
        "fk_ops_metering_usage_session__meter_definition",
        "RESTRICT",
    ),
    (
        "ops_metering_usage_record",
        "fkx_ops_metering_usage_record__tenant_meter_definition",
        "fk_ops_metering_usage_record__meter_definition",
        "RESTRICT",
    ),
    (
        "ops_metering_rated_usage",
        "fkx_ops_metering_rated_usage__tenant_meter_definition",
        "fk_ops_metering_rated_usage__meter_definition",
        "RESTRICT",
    ),
)
def _qualified(table_name: str) -> str:
    return f'"{_SCHEMA}"."{table_name}"'


def _normalize(value: Any) -> str:
    return str(value).strip().casefold()


def _stable_row_key(row: dict[str, Any]) -> tuple[Any, str]:
    return row["created_at"], str(row["id"])


def _meter_plan(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[Any, Any]]:
    """Collapse compatible tenant meters and reject unsafe global metadata."""
    unsafe: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        attributes = row.get("attributes")
        if attributes not in (None, {}):
            keys = (
                sorted(str(key) for key in attributes)
                if isinstance(attributes, dict)
                else [f"<{type(attributes).__name__}>"]
            )
            unsafe.append(f"Meter {row['id']} keys={','.join(keys)}")
        code = _normalize(row.get("code"))
        if not code:
            raise RuntimeError(f"Meter Definition {row['id']} has an empty Code.")
        grouped[code].append(row)
    if unsafe:
        raise RuntimeError(
            "Global meter migration rejected tenant Attributes; explicitly review "
            "them before retrying: " + "; ".join(sorted(unsafe))
        )

    canonical_rows: list[dict[str, Any]] = []
    mapping: dict[Any, Any] = {}
    for code, members in sorted(grouped.items()):
        semantics = {
            (_normalize(row.get("unit")), _normalize(row.get("aggregation_mode")))
            for row in members
        }
        if len(semantics) != 1:
            detail = ", ".join(
                sorted(
                    f"tenant={row['tenant_id']} id={row['id']} "
                    f"unit={row.get('unit')} aggregation={row.get('aggregation_mode')}"
                    for row in members
                )
            )
            raise RuntimeError(
                f"Conflicting meter semantics for normalized Code '{code}': {detail}"
            )
        unit, aggregation_mode = next(iter(semantics))
        if unit not in {"minute", "unit", "task"}:
            raise RuntimeError(f"Meter Code '{code}' has unsupported Unit '{unit}'.")
        if aggregation_mode not in {"sum", "max", "latest"}:
            raise RuntimeError(
                f"Meter Code '{code}' has unsupported AggregationMode "
                f"'{aggregation_mode}'."
            )
        canonical = min(members, key=_stable_row_key)
        canonical_id = canonical["id"]
        mapping.update({row["id"]: canonical_id for row in members})
        canonical_rows.append(
            {
                "id": canonical_id,
                "created_at": canonical["created_at"],
                "updated_at": canonical["updated_at"],
                "row_version": canonical["row_version"],
                "code": code,
                "unit": unit,
                "aggregation_mode": aggregation_mode,
                "description": canonical.get("description"),
                "is_active": any(bool(row.get("is_active")) for row in members),
                "attributes": None,
            }
        )
    return canonical_rows, mapping


def _validate_price_meter_contracts(
    price_rows: list[dict[str, Any]],
    canonical_rows: list[dict[str, Any]],
) -> None:
    meters = {row["code"]: row for row in canonical_rows}
    conflicts: list[str] = []
    for price in price_rows:
        price_type = str(price.get("price_type"))
        meter_code = price.get("meter_code")
        usage_unit = price.get("usage_unit")
        if price_type != "metered":
            if meter_code is not None or usage_unit is not None:
                conflicts.append(
                    f"Price {price['id']} is unmetered but has meter snapshots"
                )
            continue
        code = _normalize(meter_code) if meter_code is not None else ""
        meter = meters.get(code)
        if meter is None:
            conflicts.append(
                f"Price {price['id']} references absent meter Code '{code}'"
            )
            continue
        if not meter.get("is_active"):
            conflicts.append(
                f"Price {price['id']} references inactive meter Code '{code}'"
            )
        if _normalize(usage_unit) != meter["unit"]:
            conflicts.append(
                f"Price {price['id']} UsageUnit '{usage_unit}' conflicts with "
                f"meter Unit '{meter['unit']}'"
            )
    if conflicts:
        raise RuntimeError(
            "Billing Price meter contracts are incompatible: "
            + "; ".join(sorted(conflicts))
        )


def _load_rows(table_name: str) -> list[dict[str, Any]]:
    rows = op.get_bind().execute(
        sa.text(f"SELECT * FROM {_qualified(table_name)} ORDER BY created_at, id")
    )
    return [dict(row._mapping) for row in rows]


def _create_global_meter_table() -> None:
    op.create_table(
        "billing_meter_definition",
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
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("unit", postgresql.CITEXT(length=32), nullable=False),
        sa.Column(
            "aggregation_mode",
            postgresql.CITEXT(length=32),
            server_default=sa.text("'sum'"),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_billing_meter_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "unit IN ('minute', 'unit', 'task')",
            name="ck_billing_meter_definition__unit",
        ),
        sa.CheckConstraint(
            "aggregation_mode IN ('sum', 'max', 'latest')",
            name="ck_billing_meter_definition__aggregation_mode",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_billing_meter_definition__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_meter_definition"),
        sa.UniqueConstraint("code", name="ux_billing_meter_definition__code"),
        schema=_SCHEMA,
    )
    for column_name in ("unit", "aggregation_mode", "is_active"):
        op.create_index(
            op.f(f"ix_mugen_billing_meter_definition_{column_name}"),
            "billing_meter_definition",
            [column_name],
            schema=_SCHEMA,
        )


def _create_backups() -> None:
    op.create_table(
        "billing_meter_legacy_definition",
        sa.Column("legacy_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_id", sa.Uuid(), nullable=False),
        sa.Column("row_data", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("legacy_id", name="pk_billing_meter_legacy_definition"),
        schema=_SCHEMA,
    )
    op.create_table(
        "billing_meter_legacy_reference",
        sa.Column("table_name", sa.String(length=128), nullable=False),
        sa.Column("row_id", sa.Uuid(), nullable=False),
        sa.Column("legacy_meter_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_meter_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint(
            "table_name", "row_id", name="pk_billing_meter_legacy_reference"
        ),
        schema=_SCHEMA,
    )


def _install_touch_trigger(table_name: str) -> None:
    op.execute(f"""
        CREATE OR REPLACE TRIGGER tr_touch_updated_at_row_version__{table_name}
        BEFORE UPDATE ON {_qualified(table_name)}
        FOR EACH ROW EXECUTE FUNCTION util.tg_touch_updated_at_row_version()
        """)


def _create_legacy_meter_view() -> None:
    """Expose canonical meters through the deprecated tenant read route."""
    op.execute(f"""
        CREATE VIEW {_qualified('ops_metering_meter_definition_compat')} AS
        SELECT
            meter.id,
            meter.created_at,
            meter.updated_at,
            meter.row_version,
            tenant.id AS tenant_id,
            meter.code,
            meter.unit,
            meter.aggregation_mode,
            meter.description,
            meter.is_active,
            meter.attributes,
            true AS is_deprecated,
            'BillingMeterDefinitions'::varchar(64) AS successor_entity_set
        FROM {_qualified('billing_meter_definition')} AS meter
        CROSS JOIN {_qualified('admin_tenant')} AS tenant
        WHERE tenant.deleted_at IS NULL
        """)


def upgrade() -> None:
    """Move tenant meter semantics into one canonical global catalog."""
    if context.is_offline_mode():
        _LOG.warning("Skipping data-dependent global meter cutover offline.")
        return

    table_names = [
        "ops_metering_meter_definition",
        "billing_price",
        "billing_entitlement_bucket",
        "billing_usage_event",
        *(item[0] for item in _METER_REFERENCE_TABLES),
    ]
    op.execute(
        "LOCK TABLE "
        + ", ".join(_qualified(name) for name in table_names)
        + " IN ACCESS EXCLUSIVE MODE"
    )
    meter_rows = _load_rows("ops_metering_meter_definition")
    price_rows = _load_rows("billing_price")
    canonical_rows, mapping = _meter_plan(meter_rows)
    _validate_price_meter_contracts(price_rows, canonical_rows)

    _create_global_meter_table()
    _create_backups()
    conn = op.get_bind()
    if canonical_rows:
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_meter_definition')}
                    (id, created_at, updated_at, row_version, code, unit,
                     aggregation_mode, description, is_active, attributes)
                VALUES
                    (:id, :created_at, :updated_at, :row_version, :code, :unit,
                     :aggregation_mode, :description, :is_active,
                     CAST(:attributes AS jsonb))
            """),
            canonical_rows,
        )
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_meter_legacy_definition')}
                    (legacy_id, tenant_id, canonical_id, row_data)
                SELECT id, tenant_id, :canonical_id, to_jsonb(meter_row)
                FROM {_qualified('ops_metering_meter_definition')} AS meter_row
                WHERE id = :legacy_id
            """),
            [
                {"legacy_id": legacy_id, "canonical_id": canonical_id}
                for legacy_id, canonical_id in mapping.items()
            ],
        )

    for table_name, old_fk, new_fk, ondelete in _METER_REFERENCE_TABLES:
        table = _qualified(table_name)
        conn.execute(
            sa.text(f"""
                INSERT INTO {_qualified('billing_meter_legacy_reference')}
                    (table_name, row_id, legacy_meter_id, canonical_meter_id)
                SELECT :table_name, child.id, child.meter_definition_id,
                       legacy.canonical_id
                FROM {table} AS child
                JOIN {_qualified('billing_meter_legacy_definition')} AS legacy
                  ON legacy.legacy_id = child.meter_definition_id
            """),
            {"table_name": table_name},
        )
        stale = conn.execute(sa.text(f"""
                SELECT child.id, child.meter_definition_id
                FROM {table} AS child
                LEFT JOIN {_qualified('billing_meter_legacy_definition')} AS legacy
                  ON legacy.legacy_id = child.meter_definition_id
                WHERE legacy.legacy_id IS NULL
                ORDER BY child.id
            """)).all()
        if stale:
            raise RuntimeError(
                f"{table_name} has meter references absent from the tenant catalog: "
                + ", ".join(f"{row[0]}->{row[1]}" for row in stale)
            )
        op.drop_constraint(old_fk, table_name, schema=_SCHEMA, type_="foreignkey")
        op.execute(f"""
            UPDATE {table} AS child
            SET meter_definition_id = legacy.canonical_id
            FROM {_qualified('billing_meter_legacy_definition')} AS legacy
            WHERE child.meter_definition_id = legacy.legacy_id
        """)
        op.create_foreign_key(
            new_fk,
            table_name,
            "billing_meter_definition",
            ["meter_definition_id"],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete=ondelete,
        )

    op.drop_table("ops_metering_meter_definition", schema=_SCHEMA)
    op.execute(f'DROP TYPE IF EXISTS "{_SCHEMA}"."ops_metering_meter_unit"')
    op.execute(f'DROP TYPE IF EXISTS "{_SCHEMA}"."ops_metering_aggregation_mode"')

    op.add_column(
        "billing_price",
        sa.Column("meter_definition_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_billing_price__meter_definition",
        "billing_price",
        "billing_meter_definition",
        ["meter_definition_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.execute(f"""
        UPDATE {_qualified('billing_price')} AS price
        SET meter_definition_id = meter.id,
            meter_code = meter.code,
            usage_unit = meter.unit
        FROM {_qualified('billing_meter_definition')} AS meter
        WHERE price.price_type = 'metered'
          AND lower(btrim(price.meter_code)) = lower(meter.code)
    """)
    op.create_check_constraint(
        "ck_billing_price__meter_snapshot_complete",
        "billing_price",
        "(meter_definition_id IS NULL) = (meter_code IS NULL) AND "
        "(meter_definition_id IS NULL) = (usage_unit IS NULL)",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__metered_definition_required",
        "billing_price",
        "price_type <> 'metered' OR meter_definition_id IS NOT NULL",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_billing_price__unmetered_definition_omitted",
        "billing_price",
        "price_type = 'metered' OR meter_definition_id IS NULL",
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_billing_price_meter_definition_id"),
        "billing_price",
        ["meter_definition_id"],
        schema=_SCHEMA,
    )

    for table_name in ("billing_entitlement_bucket", "billing_usage_event"):
        op.add_column(
            table_name,
            sa.Column("meter_definition_id", sa.Uuid(), nullable=True),
            schema=_SCHEMA,
        )
        op.create_foreign_key(
            f"fk_{table_name}__meter_definition",
            table_name,
            "billing_meter_definition",
            ["meter_definition_id"],
            ["id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete="RESTRICT",
        )
        op.execute(f"""
            UPDATE {_qualified(table_name)} AS child
            SET meter_definition_id = meter.id,
                meter_code = meter.code
            FROM {_qualified('billing_meter_definition')} AS meter
            WHERE lower(btrim(child.meter_code)) = lower(meter.code)
        """)
        op.create_index(
            op.f(f"ix_mugen_{table_name}_meter_definition_id"),
            table_name,
            ["meter_definition_id"],
            schema=_SCHEMA,
        )

    _install_touch_trigger("billing_meter_definition")
    _create_legacy_meter_view()


def _recreate_tenant_meter_table() -> None:
    meter_unit = postgresql.ENUM(
        "minute",
        "unit",
        "task",
        name="ops_metering_meter_unit",
        schema=_SCHEMA,
        create_type=False,
    )
    aggregation_mode = postgresql.ENUM(
        "sum",
        "max",
        "latest",
        name="ops_metering_aggregation_mode",
        schema=_SCHEMA,
        create_type=False,
    )
    bind = op.get_bind()
    meter_unit.create(bind, checkfirst=True)
    aggregation_mode.create(bind, checkfirst=True)
    op.create_table(
        "ops_metering_meter_definition",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("unit", meter_unit, nullable=False),
        sa.Column("aggregation_mode", aggregation_mode, nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            name="fk_ops_metering_meter_definition__tenant_id__admin_tenant",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_metering_meter_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_metering_meter_definition__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_metering_meter_definition"),
        sa.UniqueConstraint(
            "tenant_id", "id", name="ux_ops_metering_meter_definition__tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="ux_ops_metering_meter_definition__tenant_code"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_metering_meter_definition__tenant_active",
        "ops_metering_meter_definition",
        ["tenant_id", "is_active"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Restore exact tenant meters only when no post-cutover rows exist."""
    if context.is_offline_mode():
        _LOG.warning("Skipping data-dependent global meter downgrade offline.")
        return
    op.execute(
        f"DROP VIEW IF EXISTS " f"{_qualified('ops_metering_meter_definition_compat')}"
    )
    conn = op.get_bind()
    for table_name, _old_fk, new_fk, _ondelete in _METER_REFERENCE_TABLES:
        missing = (
            conn.execute(
                sa.text(f"""
                SELECT child.id
                FROM {_qualified(table_name)} AS child
                LEFT JOIN {_qualified('billing_meter_legacy_reference')} AS legacy
                  ON legacy.table_name = :table_name AND legacy.row_id = child.id
                WHERE legacy.row_id IS NULL
                ORDER BY child.id
                LIMIT 20
            """),
                {"table_name": table_name},
            )
            .scalars()
            .all()
        )
        if missing:
            raise RuntimeError(
                f"Cannot downgrade: {table_name} contains post-cutover rows: "
                + ", ".join(str(value) for value in missing)
            )
        op.drop_constraint(new_fk, table_name, schema=_SCHEMA, type_="foreignkey")

    _recreate_tenant_meter_table()
    op.execute(f"""
        INSERT INTO {_qualified('ops_metering_meter_definition')}
        SELECT (
            jsonb_populate_record(
                NULL::{_qualified('ops_metering_meter_definition')}, row_data
            )
        ).*
        FROM {_qualified('billing_meter_legacy_definition')}
    """)

    for table_name, old_fk, _new_fk, ondelete in _METER_REFERENCE_TABLES:
        op.execute(f"""
            UPDATE {_qualified(table_name)} AS child
            SET meter_definition_id = legacy.legacy_meter_id
            FROM {_qualified('billing_meter_legacy_reference')} AS legacy
            WHERE legacy.table_name = '{table_name}'
              AND legacy.row_id = child.id
        """)
        op.create_foreign_key(
            old_fk,
            table_name,
            "ops_metering_meter_definition",
            ["tenant_id", "meter_definition_id"],
            ["tenant_id", "id"],
            source_schema=_SCHEMA,
            referent_schema=_SCHEMA,
            ondelete=ondelete,
        )

    for table_name in ("billing_usage_event", "billing_entitlement_bucket"):
        op.drop_index(
            op.f(f"ix_mugen_{table_name}_meter_definition_id"),
            table_name=table_name,
            schema=_SCHEMA,
        )
        op.drop_constraint(
            f"fk_{table_name}__meter_definition",
            table_name,
            schema=_SCHEMA,
            type_="foreignkey",
        )
        op.drop_column(table_name, "meter_definition_id", schema=_SCHEMA)

    op.drop_index(
        op.f("ix_mugen_billing_price_meter_definition_id"),
        table_name="billing_price",
        schema=_SCHEMA,
    )
    for constraint_name in (
        "ck_billing_price__unmetered_definition_omitted",
        "ck_billing_price__metered_definition_required",
        "ck_billing_price__meter_snapshot_complete",
    ):
        op.drop_constraint(
            constraint_name,
            "billing_price",
            schema=_SCHEMA,
            type_="check",
        )
    op.drop_constraint(
        "fk_billing_price__meter_definition",
        "billing_price",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("billing_price", "meter_definition_id", schema=_SCHEMA)
    op.execute(
        f"DROP TRIGGER IF EXISTS "
        "tr_touch_updated_at_row_version__billing_meter_definition "
        f"ON {_qualified('billing_meter_definition')}"
    )
    op.drop_table("billing_meter_definition", schema=_SCHEMA)
    op.drop_table("billing_meter_legacy_reference", schema=_SCHEMA)
    op.drop_table("billing_meter_legacy_definition", schema=_SCHEMA)
