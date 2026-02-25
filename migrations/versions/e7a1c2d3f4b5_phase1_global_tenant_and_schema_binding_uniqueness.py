"""phase1 global tenant and schema binding uniqueness remediation

Revision ID: e7a1c2d3f4b5
Revises: c7d3e9f5a1b2
Create Date: 2026-02-25 13:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from mugen.core.plugin.acp.constants import (
    GLOBAL_TENANT_ID,
    GLOBAL_TENANT_NAME,
    GLOBAL_TENANT_SLUG,
)

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f4b5"
down_revision: Union[str, Sequence[str], None] = "c7d3e9f5a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO mugen.admin_tenant (
            id,
            name,
            slug,
            status,
            deleted_at,
            deleted_by_user_id
        )
        VALUES (
            '{GLOBAL_TENANT_ID}'::uuid,
            '{GLOBAL_TENANT_NAME}',
            '{GLOBAL_TENANT_SLUG}',
            'active',
            NULL,
            NULL
        )
        ON CONFLICT (id) DO UPDATE
           SET status = 'active',
               deleted_at = NULL,
               deleted_by_user_id = NULL;
        """
    )

    op.execute(
        "DROP INDEX IF EXISTS mugen.ux_schema_binding__tenant_target_kind_active;"
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY
                        tenant_id,
                        target_namespace,
                        target_entity_set,
                        binding_kind
                    ORDER BY updated_at DESC, id DESC
                ) AS rn
            FROM mugen.admin_schema_binding
            WHERE is_active = true
              AND target_action IS NULL
        )
        UPDATE mugen.admin_schema_binding b
           SET is_active = false
          FROM ranked r
         WHERE b.id = r.id
           AND r.rn > 1;
        """
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY
                        tenant_id,
                        target_namespace,
                        target_entity_set,
                        target_action,
                        binding_kind
                    ORDER BY updated_at DESC, id DESC
                ) AS rn
            FROM mugen.admin_schema_binding
            WHERE is_active = true
              AND target_action IS NOT NULL
        )
        UPDATE mugen.admin_schema_binding b
           SET is_active = false
          FROM ranked r
         WHERE b.id = r.id
           AND r.rn > 1;
        """
    )

    op.create_index(
        "ux_schema_binding__tenant_target_kind_active_no_action",
        "admin_schema_binding",
        [
            "tenant_id",
            "target_namespace",
            "target_entity_set",
            "binding_kind",
        ],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_active AND target_action IS NULL"),
    )
    op.create_index(
        "ux_schema_binding__tenant_target_kind_active_with_action",
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
        postgresql_where=sa.text("is_active AND target_action IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_schema_binding__tenant_target_kind_active_with_action",
        table_name="admin_schema_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_schema_binding__tenant_target_kind_active_no_action",
        table_name="admin_schema_binding",
        schema=_SCHEMA,
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
        postgresql_where=sa.text("is_active"),
    )
