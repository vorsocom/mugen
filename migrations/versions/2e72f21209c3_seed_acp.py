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
- This migration does not delete seeded rows on downgrade (no-op).

Revision ID: 2e72f21209c3
Revises: a93a6eca4b3a
Create Date: 2025-12-16 18:21:41.068774

"""

from typing import Sequence, Union
import logging

from alembic import context
from alembic import op

from mugen.core.plugin.acp.migration.apply_manifest import apply_manifest
from mugen.core.plugin.acp.migration.loader import contribute_all
from mugen.core.plugin.acp.sdk.registry import AdminRegistry

# Set up a logger for this specific script
log = logging.getLogger(__name__)

# revision identifiers, used by Alembic.
revision: str = "2e72f21209c3"
down_revision: Union[str, Sequence[str], None] = "a93a6eca4b3a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SCHEMA = "mugen"


# pylint: disable=no-member
def upgrade() -> None:
    """Seed ACP control-plane data if enabled by configuration."""

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

    conn = op.get_bind()

    reg = AdminRegistry(strict_permission_decls=True)
    contribute_all(reg, mugen_cfg=mugen_cfg)

    manifest = reg.build_seed_manifest()
    apply_manifest(conn, manifest, schema=_SCHEMA)


def downgrade() -> None:
    """No-op: ACP seed data is not removed on downgrade."""
