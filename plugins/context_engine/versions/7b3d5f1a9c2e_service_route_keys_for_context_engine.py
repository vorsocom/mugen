"""service route keys for context engine

Revision ID: 7b3d5f1a9c2e
Revises: 6d4e9a1b2c3d
Create Date: 2026-03-10 10:05:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7b3d5f1a9c2e"
down_revision: Union[str, Sequence[str], None] = "6d4e9a1b2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "context_engine_context_profile",
        sa.Column(
            "service_route_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "context_engine_context_contributor_binding",
        sa.Column(
            "service_route_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "context_engine_context_source_binding",
        sa.Column(
            "service_route_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
    )

    op.create_check_constraint(
        "ck_ctxeng_profile__service_route_nonempty_if_set",
        "context_engine_context_profile",
        "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
    )
    op.create_check_constraint(
        "ck_ctxeng_contributor_binding__service_route_nonempty_if_set",
        "context_engine_context_contributor_binding",
        "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
    )
    op.create_check_constraint(
        "ck_ctxeng_source_binding__service_route_nonempty_if_set",
        "context_engine_context_source_binding",
        "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
    )

    op.create_index(
        "ix_context_engine_context_profile_service_route_key",
        "context_engine_context_profile",
        ["service_route_key"],
    )
    op.create_index(
        "ix_context_engine_context_contributor_binding_service_route_key",
        "context_engine_context_contributor_binding",
        ["service_route_key"],
    )
    op.create_index(
        "ix_context_engine_context_source_binding_service_route_key",
        "context_engine_context_source_binding",
        ["service_route_key"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_context_engine_context_source_binding_service_route_key",
        table_name="context_engine_context_source_binding",
    )
    op.drop_index(
        "ix_context_engine_context_contributor_binding_service_route_key",
        table_name="context_engine_context_contributor_binding",
    )
    op.drop_index(
        "ix_context_engine_context_profile_service_route_key",
        table_name="context_engine_context_profile",
    )

    op.drop_constraint(
        "ck_ctxeng_source_binding__service_route_nonempty_if_set",
        "context_engine_context_source_binding",
        type_="check",
    )
    op.drop_constraint(
        "ck_ctxeng_contributor_binding__service_route_nonempty_if_set",
        "context_engine_context_contributor_binding",
        type_="check",
    )
    op.drop_constraint(
        "ck_ctxeng_profile__service_route_nonempty_if_set",
        "context_engine_context_profile",
        type_="check",
    )

    op.drop_column("context_engine_context_source_binding", "service_route_key")
    op.drop_column("context_engine_context_contributor_binding", "service_route_key")
    op.drop_column("context_engine_context_profile", "service_route_key")
