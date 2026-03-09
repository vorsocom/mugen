"""add persona to context profiles

Revision ID: 0d8f7e9c4b11
Revises: 9d1a6d3a3c30
Create Date: 2026-03-09 11:30:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0d8f7e9c4b11"
down_revision: Union[str, Sequence[str], None] = "9d1a6d3a3c30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "context_engine_context_profile",
        sa.Column(
            "client_profile_key",
            postgresql.CITEXT(length=64),
            nullable=True,
        ),
    )
    op.add_column(
        "context_engine_context_profile",
        sa.Column("persona", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_context_engine_context_profile_client_profile_key",
        "context_engine_context_profile",
        ["client_profile_key"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_context_engine_context_profile_client_profile_key",
        table_name="context_engine_context_profile",
    )
    op.drop_column("context_engine_context_profile", "persona")
    op.drop_column("context_engine_context_profile", "client_profile_key")
