"""Enforce one active retention class per tenant/resource type.

Revision ID: f1a9b7c3d5e2
Revises: aa6d5f4c3b2e
Create Date: 2026-02-26 11:30:00.000000

"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a9b7c3d5e2"
down_revision: Union[str, Sequence[str], None] = "aa6d5f4c3b2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"
_TABLE = "ops_governance_retention_class"
_INDEX = "ux_ops_gov_retention_class__tenant_resource_active"


def _guard_duplicate_active_rows() -> None:
    if context.is_offline_mode():
        return

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"""
            SELECT
                tenant_id::text AS tenant_id,
                lower(resource_type::text) AS resource_type,
                COUNT(*) AS active_count
            FROM {_SCHEMA}.{_TABLE}
            WHERE is_active IS TRUE
            GROUP BY tenant_id, lower(resource_type::text)
            HAVING COUNT(*) > 1
            ORDER BY tenant_id, resource_type
            LIMIT 10
            """
        )
    ).mappings().all()

    if not rows:
        return

    sample = ", ".join(
        f"{row['tenant_id']}/{row['resource_type']}({row['active_count']})"
        for row in rows
    )
    raise RuntimeError(
        "Cannot enforce unique active retention classes. "
        "Resolve duplicate active rows first for tenant/resource_type. "
        f"Examples: {sample}"
    )


def upgrade() -> None:
    """Validate existing rows, then enforce active-class uniqueness."""
    _guard_duplicate_active_rows()
    op.create_index(
        _INDEX,
        _TABLE,
        ["tenant_id", "resource_type"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    """Drop the active-class uniqueness index."""
    op.drop_index(
        _INDEX,
        table_name=_TABLE,
        schema=_SCHEMA,
    )
