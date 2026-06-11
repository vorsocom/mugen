"""Re-apply ACP seed manifest for currently enabled plugins.

Usage:
  python -m mugen.core.plugin.acp.migration.reseed_manifest \
    --plugin-namespace com.vorsocomputing.mugen.billing
"""

from __future__ import annotations

import argparse
import importlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from mugen.core.contract.migration_config import (
    load_mugen_config,
    resolve_mugen_config_path,
)
from mugen.core.plugin.acp.migration.loader import contribute_all
from mugen.core.plugin.acp.sdk.registry import AdminRegistry
from mugen.core.plugin.acp.utility.identity import resolve_acp_admin_namespace
from mugen.core.utility.rdbms_schema import resolve_core_rdbms_schema

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAMESPACE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


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


def _apply_manifest(conn, manifest, *, schema: str) -> None:  # noqa: ANN001
    module = importlib.import_module("mugen.core.plugin.acp.migration.apply_manifest")
    module.apply_manifest(conn, manifest, schema=schema)


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
    mugen_cfg: dict[str, Any],
    schema: str | None,
    plugin_namespace: str | None,
    dry_run: bool,
) -> int:
    resolved_schema = (
        _validate_identifier(schema, "schema name")
        if schema
        else resolve_core_rdbms_schema(mugen_cfg)
    )
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
        conn.execute(text(f"SET search_path TO {resolved_schema}, public"))
        _apply_manifest(conn, manifest, schema=resolved_schema)

        print("APPLY_MANIFEST_OK")
        print(f"manifest.permission_objects={len(manifest.permission_objects)}")
        print(f"manifest.permission_types={len(manifest.permission_types)}")
        print(f"manifest.global_roles={len(manifest.global_roles)}")
        print(f"manifest.default_global_grants={len(manifest.default_global_grants)}")

        if plugin_namespace:
            pobj_count, grant_count = _fetch_plugin_grant_counts(
                conn,
                schema=resolved_schema,
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
        "--config-file",
        dest="config_file",
        default=None,
        help="Path to mugen TOML config (default: mugen.toml).",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help=(
            "Target DB schema for ACP tables "
            "(default: rdbms.migration_tracks.core.schema)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root directory for relative config paths (default: current directory).",
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
    try:
        repo_root = Path(args.repo_root).resolve()
        config_path = resolve_mugen_config_path(
            args.config_file,
            repo_root=repo_root,
        )
        mugen_cfg = load_mugen_config(config_path)
        plugin_namespace = (
            _validate_namespace(args.plugin_namespace, "plugin namespace")
            if args.plugin_namespace
            else None
        )

        return reseed_manifest(
            mugen_cfg=mugen_cfg,
            schema=args.schema,
            plugin_namespace=plugin_namespace,
            dry_run=bool(args.dry_run),
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
