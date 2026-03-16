"""add context commit ledger

Revision ID: 6d4e9a1b2c3d
Revises: 0d8f7e9c4b11
Create Date: 2026-03-09 15:10:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_core_schema, resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6d4e9a1b2c3d"
down_revision: Union[str, Sequence[str], None] = "0d8f7e9c4b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CORE_SCHEMA = resolve_core_schema(default=resolve_runtime_schema())


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "context_engine_context_commit_ledger",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey(f"{_CORE_SCHEMA}.admin_tenant.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("commit_token", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "prepared_fingerprint",
            postgresql.CITEXT(length=255),
            nullable=False,
        ),
        sa.Column("commit_state", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column(
            "result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "commit_token",
            name="ux_ctxeng_commit_ledger__tenant_token",
        ),
        sa.CheckConstraint(
            "length(btrim(scope_key)) > 0",
            name="ck_ctxeng_commit_ledger__scope_key",
        ),
        sa.CheckConstraint(
            "length(btrim(commit_token)) > 0",
            name="ck_ctxeng_commit_ledger__commit_token",
        ),
        sa.CheckConstraint(
            "length(btrim(prepared_fingerprint)) > 0",
            name="ck_ctxeng_commit_ledger__prepared_fingerprint",
        ),
        sa.CheckConstraint(
            "length(btrim(commit_state)) > 0",
            name="ck_ctxeng_commit_ledger__commit_state",
        ),
    )
    for index_name, columns in (
        ("ix_context_engine_context_commit_ledger_tenant_id", ["tenant_id"]),
        ("ix_context_engine_context_commit_ledger_scope_key", ["scope_key"]),
        ("ix_context_engine_context_commit_ledger_commit_state", ["commit_state"]),
        ("ix_context_engine_context_commit_ledger_expires_at", ["expires_at"]),
    ):
        op.create_index(index_name, "context_engine_context_commit_ledger", columns)


def downgrade() -> None:
    """Downgrade schema."""
    for index_name in (
        "ix_context_engine_context_commit_ledger_expires_at",
        "ix_context_engine_context_commit_ledger_commit_state",
        "ix_context_engine_context_commit_ledger_scope_key",
        "ix_context_engine_context_commit_ledger_tenant_id",
    ):
        op.drop_index(index_name, table_name="context_engine_context_commit_ledger")
    op.drop_table("context_engine_context_commit_ledger")
