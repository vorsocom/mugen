"""
Admin Control Plane (ACP) seed applicator (Postgres).

Applies an `AdminSeedManifest` to the database using SQLAlchemy Core +
PostgreSQL upserts.

This applicator is designed to be safe in Alembic contexts:
- no DI/container access
- no ORM model imports required
- reflects tables from the live schema
- filters outgoing row dictionaries to existing columns to tolerate schema drift
- generates UUID primary keys when tables require an `id` value and no server-side
  default is available (common when ORM defaults are Python-side only)

Tables / schema
---------------
By default, this applicator targets the admin plugin tables (schema-qualified):

- admin_permission_object
- admin_permission_type
- admin_global_role
- admin_global_permission_entry
- admin_system_flag

Tenant template tables are optional and are only reflected/applied if the manifest
contains tenant template artifacts.

Usage in Alembic
----------------
Typical migration pattern:

    from alembic import op
    from alembic import context

    from mugen.core.plugin.acp.sdk.registry import AdminRegistry
    from mugen.core.plugin.acp.loader import contribute_all
    from mugen.core.plugin.acp.sdk.apply_manifest import apply_manifest

    def upgrade():
        bind = op.get_bind()
        mugen_cfg = context.config.attributes["mugen_cfg"]

        reg = AdminRegistry(strict_permission_decls=True)
        contribute_all(reg, mugen_cfg=mugen_cfg)

        manifest = reg.build_seed_manifest()
        apply_manifest(bind, manifest, schema="mugen")

Idempotency / conflict semantics
--------------------------------
- Permission objects/types/roles are upserted on their natural keys (namespace, name)
  and may update metadata columns where present.
- Default grants are upserted on the FK triple (role_id, object_id, type_id).
- System flags are inserted if missing; on conflict only metadata (e.g., description)
  may be updated. Operator-controlled values (e.g., is_set) are not overwritten.
"""

import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence, Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mugen.core.plugin.acp.contract.sdk.seed import AdminSeedManifest

# -----------------------------
# Configuration / table naming
# -----------------------------


# pylint: disable=too-many-arguments
# pylint: disable=too-many-locals
# pylint: disable=too-many-branches
# pylint: disable=too-many-statements
# pylint: disable=too-many-instance-attributes


@dataclass(frozen=True, slots=True)
class TableNames:
    """
    Default table names + PK column assumptions for the admin plugin models.
    Override these values if your schema differs.
    """

    permission_object: str = "admin_permission_object"
    permission_type: str = "admin_permission_type"
    global_role: str = "admin_global_role"
    tenant_role_template: str = "tenant_role_template"  # optional (may not exist)
    global_grant: str = "admin_global_permission_entry"
    tenant_grant: str = "admin_tenant_permission_entry_template"  # optional
    system_flag: str = "admin_system_flag"

    # Primary key column names (UUID PK named "id" in your models)
    permission_object_pk: str = "id"
    permission_type_pk: str = "id"
    global_role_pk: str = "id"
    tenant_role_template_pk: str = "id"
    global_grant_pk: str = "id"
    tenant_grant_pk: str = "id"
    system_flag_pk: str = "id"


@dataclass(frozen=True, slots=True)
class ConflictTargets:
    """
    Default ON CONFLICT targets. Must match real UNIQUE constraints.
    Patched to use (namespace, name) for global roles per your models.
    """

    permission_object: Sequence[str] = ("namespace", "name")
    permission_type: Sequence[str] = ("namespace", "name")
    global_role: Sequence[str] = ("namespace", "name")
    tenant_role_template: Sequence[str] = ("namespace", "name")
    system_flag: Sequence[str] = ("namespace", "name")

    global_grant: Sequence[str] = (
        "global_role_id",
        "permission_object_id",
        "permission_type_id",
    )
    tenant_grant: Sequence[str] = (
        "tenant_role_template_id",
        "permission_object_id",
        "permission_type_id",
    )


# -----------------------------
# Internal helpers
# -----------------------------


def _norm_token(s: str) -> str:
    return s.strip().lower()


def _autoload_table_required(conn: Connection, schema: str, name: str) -> sa.Table:
    md = sa.MetaData(schema=schema)
    try:
        return sa.Table(name, md, autoload_with=conn)
    except sa.exc.NoSuchTableError as e:
        raise RuntimeError(f"Required table '{schema}.{name}' was not found.") from e


def _autoload_table_optional(
    conn: Connection, schema: str, name: str
) -> sa.Table | None:
    md = sa.MetaData(schema=schema)
    try:
        return sa.Table(name, md, autoload_with=conn)
    except sa.exc.NoSuchTableError:
        return None


def _require_columns(table: sa.Table, cols: Iterable[str]) -> None:
    missing = [c for c in cols if c not in table.c]
    if missing:
        raise RuntimeError(
            f"Table '{table.fullname}' is missing required columns: {missing}. "
            f"Available columns: {list(table.c.keys())}"
        )


def _filter_row_to_table(table: sa.Table, row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Remove keys not present in the reflected table to avoid insert/update failures
    when contracts include fields not present in DB schema.
    """
    return {k: v for k, v in row.items() if k in table.c}


def _maybe_add_pk(table: sa.Table, rows: list[dict], pk_col: str) -> None:
    """
    If pk_col is required (NOT NULL) and has no server default, generate UUIDs.
    Reflection won't capture ORM-side defaults, so we must supply values.
    """
    if pk_col not in table.c:
        return

    col = table.c[pk_col]

    # If DB already has a server default, do nothing.
    if col.server_default is not None:
        return

    # If nullable, also do nothing.
    if col.nullable:
        return

    # If caller already supplied pk values, keep them.
    for r in rows:
        if pk_col not in r or r[pk_col] is None:
            r[pk_col] = uuid.uuid4()


def _upsert_rows(
    conn: Connection,
    table: sa.Table,
    rows: list[dict[str, Any]],
    *,
    conflict_cols: Sequence[str],
    update_cols: Sequence[str] = (),
    pk_col: str | None = None,
) -> None:
    if not rows:
        return

    _require_columns(table, conflict_cols)

    # Filter to actual columns
    rows_f = [_filter_row_to_table(table, r) for r in rows]

    # Remove any empty rows (should not happen if required cols exist)
    rows_f = [r for r in rows_f if r]

    if not rows_f:
        return

    # Generate PK if needed
    if pk_col:
        _maybe_add_pk(table, rows_f, pk_col)

    # Only update columns that exist
    update_cols_f = tuple(c for c in update_cols if c in table.c)

    stmt = pg_insert(table).values(rows_f)

    if update_cols_f:
        stmt = stmt.on_conflict_do_update(
            index_elements=list(conflict_cols),
            set_={c: getattr(stmt.excluded, c) for c in update_cols_f},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=list(conflict_cols))

    conn.execute(stmt)


def _fetch_id_map(
    conn: Connection,
    table: sa.Table,
    pk_col: str,
    key_cols: Sequence[str],
) -> dict[tuple[str, ...], Any]:
    """
    Fetch mapping from key tuple -> PK, with normalization for CITEXT-ish columns.
    """
    _require_columns(table, [pk_col, *key_cols])

    cols = [table.c[c] for c in key_cols]
    sel = sa.select(table.c[pk_col], *cols)
    out: dict[tuple[str, ...], Any] = {}
    for row in conn.execute(sel):
        pk = row[0]
        key_raw = row[1:]
        key_norm = tuple(_norm_token(v) if isinstance(v, str) else v for v in key_raw)
        out[key_norm] = pk
    return out


def _split_key(key: str) -> tuple[str, str]:
    """
    Split "<namespace>:<name>" keys (permission object/type keys).
    """
    k = key.strip()
    if ":" not in k:
        raise ValueError(f"Invalid key '{key}': expected '<namespace>:<name>'")
    ns, name = k.split(":", 1)
    ns_n = _norm_token(ns)
    name_n = _norm_token(name)
    if not ns_n or not name_n:
        raise ValueError(f"Invalid key '{key}': empty namespace or name")
    return ns_n, name_n


# -----------------------------
# Public entrypoint
# -----------------------------


def apply_manifest(
    conn: Connection,
    manifest: AdminSeedManifest,
    *,
    schema: str = "mugen",
    tables: TableNames = TableNames(),
    conflicts: ConflictTargets = ConflictTargets(),
) -> None:
    """
    Apply a seed manifest to the database.
    """

    # --- Required tables (per your current models) ---
    t_pobj = _autoload_table_required(conn, schema, tables.permission_object)
    t_ptyp = _autoload_table_required(conn, schema, tables.permission_type)
    t_grole = _autoload_table_required(conn, schema, tables.global_role)
    t_ggrant = _autoload_table_required(conn, schema, tables.global_grant)
    t_sysflag = _autoload_table_required(conn, schema, tables.system_flag)

    # --- Optional tenant-scoped tables ---
    need_tenant = bool(manifest.tenant_role_templates) or bool(
        manifest.default_tenant_grants
    )
    t_trole = None
    t_tgrant = None
    if need_tenant:
        t_trole = _autoload_table_optional(conn, schema, tables.tenant_role_template)
        t_tgrant = _autoload_table_optional(conn, schema, tables.tenant_grant)
        if t_trole is None or t_tgrant is None:
            raise RuntimeError(
                "Manifest includes tenant role templates/grants, but required tenant"
                f" tables were not found in schema '{schema}'."
            )

    # --- Upsert permission objects ---
    pobj_rows = []
    for o in manifest.permission_objects:
        ns, name = _norm_token(o.namespace), _norm_token(o.name)
        base = {"namespace": ns, "name": name}
        pobj_rows.append(base)

    _upsert_rows(
        conn,
        t_pobj,
        pobj_rows,
        conflict_cols=conflicts.permission_object,
        pk_col=tables.permission_object_pk,
    )

    # --- Upsert permission types ---
    ptyp_rows = []
    for t in manifest.permission_types:
        ns, name = _norm_token(t.namespace), _norm_token(t.name)
        base = {"namespace": ns, "name": name}
        ptyp_rows.append(base)

    _upsert_rows(
        conn,
        t_ptyp,
        ptyp_rows,
        conflict_cols=conflicts.permission_type,
        pk_col=tables.permission_type_pk,
    )

    # --- Upsert global roles ---
    grole_rows = []
    for r in manifest.global_roles:
        ns, name = _norm_token(r.namespace), _norm_token(r.name)
        base = {"namespace": ns, "name": name, "display_name": r.display_name}
        grole_rows.append(base)

    _upsert_rows(
        conn,
        t_grole,
        grole_rows,
        conflict_cols=conflicts.global_role,
        pk_col=tables.global_role_pk,
    )

    # --- Resolve IDs for grants ---
    pobj_id = _fetch_id_map(
        conn, t_pobj, tables.permission_object_pk, ("namespace", "name")
    )
    ptyp_id = _fetch_id_map(
        conn, t_ptyp, tables.permission_type_pk, ("namespace", "name")
    )
    grole_id = _fetch_id_map(
        conn, t_grole, tables.global_role_pk, ("namespace", "name")
    )

    # --- Upsert global grants ---
    ggrant_rows = []
    for g in manifest.default_global_grants:
        role_ns, role_name = _split_key(g.global_role)
        pobj_ns, pobj_name = _split_key(g.permission_object)
        ptyp_ns, ptyp_name = _split_key(g.permission_type)

        gr_id = grole_id.get((_norm_token(role_ns), _norm_token(role_name)))
        po_id = pobj_id.get((_norm_token(pobj_ns), _norm_token(pobj_name)))
        pt_id = ptyp_id.get((_norm_token(ptyp_ns), _norm_token(ptyp_name)))

        if gr_id is None:
            raise RuntimeError(
                "Default global grant references unknown global role"
                f" '{g.global_role}'."
            )
        if po_id is None:
            raise RuntimeError(
                "Default global grant references unknown permission object"
                f" '{g.permission_object}'."
            )
        if pt_id is None:
            raise RuntimeError(
                "Default global grant references unknown permission type"
                f" '{g.permission_type}'."
            )

        ggrant_rows.append(
            {
                "global_role_id": gr_id,
                "permission_object_id": po_id,
                "permission_type_id": pt_id,
                "permitted": bool(g.permitted),
            }
        )

    _upsert_rows(
        conn,
        t_ggrant,
        ggrant_rows,
        conflict_cols=conflicts.global_grant,
        update_cols=("permitted",),
        pk_col=tables.global_grant_pk,
    )

    # --- Optional tenant templates/grants (only if present) ---
    if need_tenant and t_trole is not None and t_tgrant is not None:
        # Templates
        trows = []
        for r in manifest.tenant_role_templates:
            ns, name = _norm_token(r.namespace), _norm_token(r.name)
            base = {"namespace": ns, "name": name, "display_name": r.display_name}
            trows.append(base)

        _upsert_rows(
            conn,
            t_trole,
            trows,
            conflict_cols=conflicts.tenant_role_template,
            pk_col=tables.tenant_role_template_pk,
        )

        # Resolve template IDs
        trole_id = _fetch_id_map(
            conn, t_trole, tables.tenant_role_template_pk, ("namespace", "name")
        )

        # Tenant grants
        tgrows = []
        for g in manifest.default_tenant_grants:
            role_ns, role_name = _split_key(g.tenant_role_template)
            pobj_ns, pobj_name = _split_key(g.permission_object)
            ptyp_ns, ptyp_name = _split_key(g.permission_type)

            tr_id = trole_id.get((_norm_token(role_ns), _norm_token(role_name)))
            po_id = pobj_id.get((_norm_token(pobj_ns), _norm_token(pobj_name)))
            pt_id = ptyp_id.get((_norm_token(ptyp_ns), _norm_token(ptyp_name)))

            if tr_id is None:
                raise RuntimeError(
                    "Default tenant grant references unknown template"
                    f" '{g.tenant_role_template}'."
                )
            if po_id is None:
                raise RuntimeError(
                    "Default tenant grant references unknown permission object"
                    f" '{g.permission_object}'."
                )
            if pt_id is None:
                raise RuntimeError(
                    "Default tenant grant references unknown permission type"
                    f" '{g.permission_type}'."
                )

            tgrows.append(
                {
                    "tenant_role_template_id": tr_id,
                    "permission_object_id": po_id,
                    "permission_type_id": pt_id,
                    "permitted": bool(g.permitted),
                }
            )

        _upsert_rows(
            conn,
            t_tgrant,
            tgrows,
            conflict_cols=conflicts.tenant_grant,
            update_cols=("permitted",),
            pk_col=tables.tenant_grant_pk,
        )

    sysflag_rows = []
    for flag in manifest.system_flags:
        ns, name = _norm_token(flag.namespace), _norm_token(flag.name)
        base = {
            "namespace": ns,
            "name": name,
            "description": flag.description,
            "is_set": flag.is_set,
        }
        sysflag_rows.append(base)

    _upsert_rows(
        conn,
        t_sysflag,
        sysflag_rows,
        conflict_cols=conflicts.system_flag,
        update_cols=("description",),
        pk_col=tables.system_flag_pk,
    )
