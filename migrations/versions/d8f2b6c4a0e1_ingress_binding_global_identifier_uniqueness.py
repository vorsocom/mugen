"""Align active ingress identifier uniqueness with global routing.

Revision ID: d8f2b6c4a0e1
Revises: a6c1d8e4f2b7
Create Date: 2026-09-05 00:00:00.000000

Existing cross-tenant collisions deliberately fail the unique-index creation.
Operators must verify channel ownership and deactivate invalid bindings before
retrying; the migration never chooses an owner or discards runtime records.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

from migrations.schema_contract import resolve_runtime_schema

revision: str = "d8f2b6c4a0e1"
down_revision: str | Sequence[str] | None = "a6c1d8e4f2b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = resolve_runtime_schema()
_TABLE = "channel_orchestration_ingress_binding"


def upgrade() -> None:
    op.create_index(
        "ux_chorch_ingress_binding__ci_active_unique",
        _TABLE,
        ["channel_key", "identifier_type", "identifier_value"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_active = true"),
    )
    op.drop_index(
        "ux_chorch_ingress_binding__tci_active_unique",
        table_name=_TABLE,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.create_index(
        "ux_chorch_ingress_binding__tci_active_unique",
        _TABLE,
        ["tenant_id", "channel_key", "identifier_type", "identifier_value"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_active = true"),
    )
    op.drop_index(
        "ux_chorch_ingress_binding__ci_active_unique",
        table_name=_TABLE,
        schema=_SCHEMA,
    )
