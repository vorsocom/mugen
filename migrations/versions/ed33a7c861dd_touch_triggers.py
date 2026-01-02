"""Install touch triggers.

Revision ID: ed33a7c861dd
Revises: cd8d7bce9a46
Create Date: 2025-12-16 09:49:42.773821

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ed33a7c861dd"
down_revision: Union[str, Sequence[str], None] = "cd8d7bce9a46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TOUCH_TABLES = [
    "global_permission_entry",
    "global_role",
    "global_role_membership",
    "permission_entry",
    "permission_object",
    "permission_type",
    "person",
    "refresh_token",
    "role",
    "role_membership",
    "system_flag",
    "tenant",
    "tenant_domain",
    "tenant_invitation",
    "tenant_membership",
    "user",
]


# pylint: disable=no-member
def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE SCHEMA IF NOT EXISTS util;

        CREATE OR REPLACE FUNCTION util.tg_touch_updated_at_row_version()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at := now();
            NEW.row_version := COALESCE(OLD.row_version, 0) + 1;
            RETURN NEW;
        END;
        $$;
        """
    )

    for table in _TOUCH_TABLES:
        op.execute(
            f"""
            DROP TRIGGER IF EXISTS tr_touch_admin_{table}
            ON mugen.admin_{table};

            CREATE TRIGGER tr_touch_admin_{table}
            BEFORE UPDATE ON mugen.admin_{table}
            FOR EACH ROW
            EXECUTE FUNCTION util.tg_touch_updated_at_row_version();
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in _TOUCH_TABLES:
        op.execute(
            f"DROP TRIGGER IF EXISTS tr_touch_admin_{table} ON mugen.admin_{table};"
        )
    op.execute("DROP FUNCTION IF EXISTS util.tg_touch_updated_at_row_version();")
    op.execute("DROP SCHEMA IF EXISTS util;")
