"""phase1 foundations hardening and reseed

Revision ID: c7d3e9f5a1b2
Revises: b8f2e6d4c1a9
Create Date: 2026-02-25 10:55:00.000000

"""

from typing import Sequence, Union
import logging

from alembic import context
from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from migrations.schema_contract import rewrite_mugen_schema_sql

# revision identifiers, used by Alembic.
revision: str = "c7d3e9f5a1b2"
down_revision: Union[str, Sequence[str], None] = "b8f2e6d4c1a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)


def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def _execute(statement) -> None:
    if isinstance(statement, str):
        op.execute(_sql(statement))
        return
    op.execute(statement)


def _reseed_acp_manifest() -> None:
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


def upgrade() -> None:
    # Ensure at most one active schema version per (tenant_id, key)
    # before adding the partial unique index.
    _execute("""
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY tenant_id, key
                    ORDER BY version DESC, updated_at DESC, id DESC
                ) AS rn
            FROM mugen.admin_schema_definition
            WHERE status = 'active'
        )
        UPDATE mugen.admin_schema_definition d
           SET status = 'inactive',
               activated_at = NULL,
               activated_by_user_id = NULL
          FROM ranked r
         WHERE d.id = r.id
           AND r.rn > 1;
        """)

    # Ensure at most one active binding per target tuple
    # before adding the partial unique index.
    _execute("""
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY
                        tenant_id,
                        target_namespace,
                        target_entity_set,
                        COALESCE(target_action::text, ''),
                        binding_kind
                    ORDER BY updated_at DESC, id DESC
                ) AS rn
            FROM mugen.admin_schema_binding
            WHERE is_active = true
        )
        UPDATE mugen.admin_schema_binding b
           SET is_active = false
          FROM ranked r
         WHERE b.id = r.id
           AND r.rn > 1;
        """)

    op.create_index(
        "ux_schema_definition__tenant_key_active",
        "admin_schema_definition",
        ["tenant_id", "key"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("status = 'active'"),
    )
    op.create_index(
        "ux_schema_binding__tenant_target_kind_active",
        "admin_schema_binding",
        [
            "tenant_id",
            "target_namespace",
            "target_entity_set",
            "target_action",
            "binding_kind",
        ],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("is_active"),
    )

    _reseed_acp_manifest()


def downgrade() -> None:
    op.drop_index(
        "ux_schema_binding__tenant_target_kind_active",
        table_name="admin_schema_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_schema_definition__tenant_key_active",
        table_name="admin_schema_definition",
        schema=_SCHEMA,
    )
