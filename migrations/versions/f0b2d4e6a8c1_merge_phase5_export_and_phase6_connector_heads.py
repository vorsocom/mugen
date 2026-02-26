"""merge phase5 export and phase6 connector heads

Revision ID: f0b2d4e6a8c1
Revises: c6e2a4b8d0f1, e3b5d7f9a1c2
Create Date: 2026-02-26 18:25:00.000000

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "f0b2d4e6a8c1"
down_revision: Union[str, Sequence[str], None] = (
    "c6e2a4b8d0f1",
    "e3b5d7f9a1c2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge revision: no schema changes."""


def downgrade() -> None:
    """Merge revision: no schema changes."""
