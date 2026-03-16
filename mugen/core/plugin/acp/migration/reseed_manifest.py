"""Re-apply ACP seed manifest for currently enabled plugins.

Usage:
  python -m mugen.core.plugin.acp.migration.reseed_manifest \
    --config mugen.toml \
    --plugin-namespace com.vorsocomputing.mugen.billing
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import tomlkit
from sqlalchemy import create_engine, text

from mugen.core.plugin.acp.migration.apply_manifest import apply_manifest
from mugen.core.plugin.acp.migration.loader import contribute_all
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.utility.identity import resolve_acp_admin_namespace

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAMESPACE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _load_cfg(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf8") as handle:
        return tomlkit.loads(handle.read()).value


def _validate_identifier(name: str, label: str) -> str:
    if not _IDENT_RE.fullmatch(name):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _validate_namespace(name: str, label: str) -> str:
    if not _NAMESPACE_RE.fullmatch(name):
        raise ValueError(f"Invalid {label}: {name!r}")
    return name


def _build_manifest(mugen_cfg: dict[str, Any]):
    registry = AdminRegistry(strict_permission_decls=True)
    contribute_all(registry, mugen_cfg=mugen_cfg)
    return registry.build_seed_manifest()


def _fetch_plugin_grant_counts(
    conn,
    *,
    schema: str,
    admin_namespace: str,
    plugin_namespace: str,
) -> tuple[int, int]:
    pobj_count = conn.execute(
        text(f"""
            SELECT count(*)
            FROM {schema}.admin_permission_object
            WHERE namespace = :plugin_namespace
            """),
        {"plugin_namespace": plugin_namespace},
    ).scalar_one()

    grant_count = conn.execute(
        text(f"""
            SELECT count(*)
            FROM {schema}.admin_global_permission_entry g
            JOIN {schema}.admin_permission_object o
              ON o.id = g.permission_object_id
            JOIN {schema}.admin_global_role r
              ON r.id = g.global_role_id
            WHERE o.namespace = :plugin_namespace
              AND r.namespace = :admin_namespace
              AND r.name = 'administrator'
            """),
        {
            "plugin_namespace": plugin_namespace,
            "admin_namespace": admin_namespace,
        },
    ).scalar_one()

    return int(pobj_count), int(grant_count)


def reseed_manifest(
    *,
    config_path: Path,
    schema: str,
    plugin_namespace: str | None,
    dry_run: bool,
) -> int:
    mugen_cfg = _load_cfg(config_path)
    manifest = _build_manifest(mugen_cfg)

    if dry_run:
        print("DRY_RUN: no DB changes applied")
        print(f"manifest.permission_objects={len(manifest.permission_objects)}")
        print(f"manifest.permission_types={len(manifest.permission_types)}")
        print(f"manifest.global_roles={len(manifest.global_roles)}")
        print(f"manifest.default_global_grants={len(manifest.default_global_grants)}")
        if plugin_namespace:
            plugin_objects = [
                p
                for p in manifest.permission_objects
                if p.namespace.lower() == plugin_namespace.lower()
            ]
            plugin_grants = [
                g
                for g in manifest.default_global_grants
                if g.permission_object.lower().startswith(
                    plugin_namespace.lower() + ":"
                )
            ]
            print(f"manifest.plugin_permission_objects={len(plugin_objects)}")
            print(f"manifest.plugin_default_global_grants={len(plugin_grants)}")
        return 0

    db_url = mugen_cfg["rdbms"]["alembic"]["url"]
    admin_namespace = resolve_acp_admin_namespace(mugen_cfg, enabled_only=True)

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(f"SET search_path TO {schema}, public"))
        apply_manifest(conn, manifest, schema=schema)

        print("APPLY_MANIFEST_OK")
        print(f"manifest.permission_objects={len(manifest.permission_objects)}")
        print(f"manifest.permission_types={len(manifest.permission_types)}")
        print(f"manifest.global_roles={len(manifest.global_roles)}")
        print(f"manifest.default_global_grants={len(manifest.default_global_grants)}")

        if plugin_namespace:
            pobj_count, grant_count = _fetch_plugin_grant_counts(
                conn,
                schema=schema,
                admin_namespace=admin_namespace,
                plugin_namespace=plugin_namespace,
            )
            print(f"db.plugin_permission_objects={pobj_count}")
            print(f"db.plugin_admin_grants={grant_count}")

    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-apply ACP seed manifest for enabled plugins."
    )
    parser.add_argument(
        "--config",
        default="mugen.toml",
        help="Path to mugen TOML config (default: mugen.toml).",
    )
    parser.add_argument(
        "--schema",
        default="mugen",
        help="Target DB schema for ACP tables (default: mugen).",
    )
    parser.add_argument(
        "--plugin-namespace",
        default=None,
        help=(
            "Optional plugin namespace to verify after reseed, "
            "e.g. com.vorsocomputing.mugen.billing."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print manifest stats without applying DB changes.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    schema = _validate_identifier(args.schema, "schema name")
    plugin_namespace = (
        _validate_namespace(args.plugin_namespace, "plugin namespace")
        if args.plugin_namespace
        else None
    )

    return reseed_manifest(
        config_path=config_path,
        schema=schema,
        plugin_namespace=plugin_namespace,
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
