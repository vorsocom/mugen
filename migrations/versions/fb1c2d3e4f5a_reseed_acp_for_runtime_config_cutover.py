"""Re-apply ACP manifest for runtime-config profile contributions.

Revision ID: fb1c2d3e4f5a
Revises: fa1c2d3e4b5c
Create Date: 2026-03-08 22:15:00.000000

"""

from typing import Sequence, Union
import json
import logging

from alembic import context
from alembic import op
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "fb1c2d3e4f5a"
down_revision: Union[str, Sequence[str], None] = "fa1c2d3e4b5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)
_GLOBAL_TENANT_ID = "00000000-0000-0000-0000-000000000000"
_ACP_KMS_CAPABILITIES = (
    "kms.key.rotate",
    "kms.key.retire",
    "kms.key.destroy",
)
_ACP_KMS_SEED_SOURCE = "runtime_config_cutover_default_acp_kms_grant"


def _seed_default_acp_kms_capability_grant(conn, *, plugin_key: str) -> None:
    existing = conn.execute(
        text(
            f"""
            SELECT id
            FROM {_SCHEMA}.admin_plugin_capability_grant
            WHERE tenant_id = :tenant_id
              AND lower(plugin_key) = lower(:plugin_key)
              AND revoked_at IS NULL
            LIMIT 1
            """
        ),
        {
            "tenant_id": _GLOBAL_TENANT_ID,
            "plugin_key": plugin_key,
        },
    ).first()
    if existing is not None:
        return

    conn.execute(
        text(
            f"""
            INSERT INTO {_SCHEMA}.admin_plugin_capability_grant (
                tenant_id,
                plugin_key,
                capabilities,
                granted_by_user_id,
                attributes
            )
            VALUES (
                :tenant_id,
                :plugin_key,
                CAST(:capabilities AS jsonb),
                NULL,
                CAST(:attributes AS jsonb)
            )
            """
        ),
        {
            "tenant_id": _GLOBAL_TENANT_ID,
            "plugin_key": plugin_key,
            "capabilities": json.dumps(list(_ACP_KMS_CAPABILITIES)),
            "attributes": json.dumps(
                {
                    "seed_source": _ACP_KMS_SEED_SOURCE,
                }
            ),
        },
    )


def upgrade() -> None:
    """Apply ACP manifest so runtime config profile resources are seeded."""
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
    _seed_default_acp_kms_capability_grant(
        conn,
        plugin_key=str(acp_cfg.get("plugin_name") or acp_cfg.get("namespace")),
    )


def downgrade() -> None:
    """Delete only the default ACP KMS capability grant seeded by upgrade."""
    if context.is_offline_mode():
        return

    conn = op.get_bind()
    conn.execute(
        text(
            f"""
            DELETE FROM {_SCHEMA}.admin_plugin_capability_grant
            WHERE tenant_id = :tenant_id
              AND attributes @> CAST(:attributes AS jsonb)
            """
        ),
        {
            "tenant_id": _GLOBAL_TENANT_ID,
            "attributes": json.dumps({"seed_source": _ACP_KMS_SEED_SOURCE}),
        },
    )
