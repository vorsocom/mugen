"""knowledge scope route profile keys

Revision ID: e6f7a8b9c0d1
Revises: ff0a1b2c3d4e
Create Date: 2026-06-04 00:00:00.000000

"""

from typing import Sequence, Union
import logging

from alembic import context
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.schema_contract import resolve_runtime_schema

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "ff0a1b2c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)


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
    op.add_column(
        "knowledge_pack_knowledge_scope",
        sa.Column(
            "service_route_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "knowledge_pack_knowledge_scope",
        sa.Column(
            "client_profile_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_knowledge_scope__service_route_nonempty_if_set",
        "knowledge_pack_knowledge_scope",
        "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_knowledge_scope__client_profile_nonempty_if_set",
        "knowledge_pack_knowledge_scope",
        "client_profile_key IS NULL OR length(btrim(client_profile_key)) > 0",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_scope__service_route_key",
        "knowledge_pack_knowledge_scope",
        ["service_route_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_scope__client_profile_key",
        "knowledge_pack_knowledge_scope",
        ["client_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_scope__tenant_route_profile_active",
        "knowledge_pack_knowledge_scope",
        ["tenant_id", "service_route_key", "client_profile_key", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    _reseed_acp_manifest()


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_scope__tenant_route_profile_active",
        table_name="knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_knowledge_scope__client_profile_key",
        table_name="knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_knowledge_scope__service_route_key",
        table_name="knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_knowledge_scope__client_profile_nonempty_if_set",
        "knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_knowledge_scope__service_route_nonempty_if_set",
        "knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(
        "knowledge_pack_knowledge_scope",
        "client_profile_key",
        schema=_SCHEMA,
    )
    op.drop_column(
        "knowledge_pack_knowledge_scope",
        "service_route_key",
        schema=_SCHEMA,
    )
