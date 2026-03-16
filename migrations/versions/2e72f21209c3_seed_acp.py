"""Seed Admin Control Plane (ACP) policy data.

This migration is intentionally data-only (no schema changes). It applies the ACP
seed manifest (permission objects/types, roles, default grants, system flags)
when explicitly enabled by configuration.

Configuration
-------------
ACP is an extension of muGen, so its gating config lives under a dedicated top-level
section:

    [admin]
    seed_acp = true

Plugin discovery for contributions still uses the muGen core module system under
`mugen.modules...` (see `contribute_all`), but seeding is gated by `admin.seed_acp`.

Operational notes
-----------------
- Seeding is idempotent and safe to re-run.
- Downgrade removes ACP rows represented by the generated seed manifest.

Revision ID: 2e72f21209c3
Revises: a93a6eca4b3a
Create Date: 2025-12-16 18:21:41.068774

"""

from typing import Sequence, Union
import logging

from alembic import context
from alembic import op
from migrations.schema_contract import rewrite_mugen_schema_sql
from migrations.schema_contract import resolve_runtime_schema

# Set up a logger for this specific script
log = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "2e72f21209c3"
down_revision: Union[str, Sequence[str], None] = "a93a6eca4b3a"
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


# pylint: disable=no-member
def upgrade() -> None:
    """Seed ACP control-plane data if enabled by configuration."""
    if context.is_offline_mode():
        log.warning("Skipping ACP seeding in offline mode.")
        return

    mugen_cfg = context.config.attributes.get("mugen_cfg")

    if not mugen_cfg:
        raise RuntimeError(
            "mugen_cfg was not provided to Alembic env; cannot seed ACP."
        )

    acp_cfg = mugen_cfg.get("acp", {})
    seed_acp = acp_cfg.get("seed_acp", False)

    if not isinstance(seed_acp, bool):
        raise TypeError("admin.seed_acp must be a boolean (true/false).")

    if not seed_acp:
        log.warning("ACP seeding skipped by config.")
        return

    # Import locally to keep revision loading lightweight.
    from mugen.core.plugin.acp.migration.apply_manifest import apply_manifest
    from mugen.core.plugin.acp.migration.loader import contribute_all
    from mugen.core.plugin.acp.sdk.registry import AdminRegistry

    conn = op.get_bind()

    reg = AdminRegistry(strict_permission_decls=True)
    contribute_all(reg, mugen_cfg=mugen_cfg)

    manifest = reg.build_seed_manifest()
    apply_manifest(conn, manifest, schema=_SCHEMA)


def downgrade() -> None:
    """Remove ACP control-plane seed data."""
    if context.is_offline_mode():
        log.warning("Skipping ACP unseeding in offline mode.")
        return

    mugen_cfg = context.config.attributes.get("mugen_cfg")

    if not mugen_cfg:
        raise RuntimeError(
            "mugen_cfg was not provided to Alembic env; cannot unseed ACP."
        )

    # Import locally to keep revision loading lightweight.
    from mugen.core.plugin.acp.migration.apply_manifest import unapply_manifest
    from mugen.core.plugin.acp.migration.loader import contribute_all
    from mugen.core.plugin.acp.sdk.registry import AdminRegistry

    conn = op.get_bind()

    reg = AdminRegistry(strict_permission_decls=True)
    contribute_all(reg, mugen_cfg=mugen_cfg)

    manifest = reg.build_seed_manifest()
    unapply_manifest(conn, manifest, schema=_SCHEMA)
