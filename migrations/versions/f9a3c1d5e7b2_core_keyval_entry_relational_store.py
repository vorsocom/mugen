"""core keyval entry relational store

Revision ID: f9a3c1d5e7b2
Revises: e1f3d5b7c9a0
Create Date: 2026-02-26 23:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f9a3c1d5e7b2"
down_revision: Union[str, Sequence[str], None] = "e1f3d5b7c9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.create_table(
        "core_keyval_entry",
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.BYTEA(), nullable=False),
        sa.Column(
            "codec",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'bytes'"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(btrim(namespace)) > 0",
            name="ck_core_keyval_entry_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(entry_key)) > 0",
            name="ck_core_keyval_entry_key_nonempty",
        ),
        sa.PrimaryKeyConstraint(
            "namespace",
            "entry_key",
            name="pk_core_keyval_entry",
        ),
        schema=_SCHEMA,
    )

    op.create_index(
        "ix_core_keyval_entry_namespace_expires_at",
        "core_keyval_entry",
        ["namespace", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_core_keyval_entry_namespace_entry_key_prefix",
        "core_keyval_entry",
        ["namespace", "entry_key"],
        unique=False,
        schema=_SCHEMA,
        postgresql_ops={"entry_key": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index(
        "ix_core_keyval_entry_namespace_entry_key_prefix",
        table_name="core_keyval_entry",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_core_keyval_entry_namespace_expires_at",
        table_name="core_keyval_entry",
        schema=_SCHEMA,
    )
    op.drop_table("core_keyval_entry", schema=_SCHEMA)
