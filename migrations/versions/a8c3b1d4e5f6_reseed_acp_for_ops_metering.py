"""Re-apply ACP manifest for ops_metering contributions.

Revision ID: a8c3b1d4e5f6
Revises: f2d9c4b6a7e8
Create Date: 2026-02-13 18:20:00.000000

"""

from typing import Sequence, Union
import logging

from alembic import context
from alembic import op
from migrations.schema_contract import resolve_runtime_schema

# revision identifiers, used by Alembic.
revision: str = "a8c3b1d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f2d9c4b6a7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)


def upgrade() -> None:
    """Apply ACP manifest so newly contributed ops_metering resources are seeded."""
    if context.is_offline_mode():
        _LOG.warning("Skipping ACP reseed in offline mode.")
        return

    mugen_cfg = context.config.attributes.get("mugen_cfg")
    if not mugen_cfg:
        raise RuntimeError("mugen_cfg was not provided to Alembic env.")

    acp_cfg = mugen_cfg.get("acp", {})
    seed_acp = bool(acp_cfg.get("seed_acp", False))
    if not seed_acp:
        _LOG.warning("ACP reseed skipped by config.")
        return

    from mugen.core.plugin.acp.migration.apply_manifest import apply_manifest
    from mugen.core.plugin.acp.migration.loader import contribute_all
    from mugen.core.plugin.acp.sdk.registry import AdminRegistry

    conn = op.get_bind()
    registry = AdminRegistry(strict_permission_decls=True)
    contribute_all(registry, mugen_cfg=mugen_cfg)
    manifest = registry.build_seed_manifest()
    apply_manifest(conn, manifest, schema=_SCHEMA)


def downgrade() -> None:
    """No-op: this revision only re-applies idempotent ACP seed data."""
