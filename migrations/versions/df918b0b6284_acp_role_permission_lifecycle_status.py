"""acp_role_permission_lifecycle_status

Revision ID: df918b0b6284
Revises: e5f4d3c2b1a0
Create Date: 2026-02-23 08:08:57.824581

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "df918b0b6284"
down_revision: Union[str, Sequence[str], None] = "e5f4d3c2b1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    role_status = postgresql.ENUM(
        "active",
        "deprecated",
        name="admin_role_status",
        schema="mugen",
        create_type=False,
    )
    permission_object_status = postgresql.ENUM(
        "active",
        "deprecated",
        name="admin_permission_object_status",
        schema="mugen",
        create_type=False,
    )
    permission_type_status = postgresql.ENUM(
        "active",
        "deprecated",
        name="admin_permission_type_status",
        schema="mugen",
        create_type=False,
    )

    role_status.create(op.get_bind(), checkfirst=True)
    permission_object_status.create(op.get_bind(), checkfirst=True)
    permission_type_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "admin_role",
        sa.Column(
            "status",
            role_status,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_admin_role_status"),
        "admin_role",
        ["status"],
        unique=False,
        schema="mugen",
    )

    op.add_column(
        "admin_permission_object",
        sa.Column(
            "status",
            permission_object_status,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_admin_permission_object_status"),
        "admin_permission_object",
        ["status"],
        unique=False,
        schema="mugen",
    )

    op.add_column(
        "admin_permission_type",
        sa.Column(
            "status",
            permission_type_status,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        schema="mugen",
    )
    op.create_index(
        op.f("ix_mugen_admin_permission_type_status"),
        "admin_permission_type",
        ["status"],
        unique=False,
        schema="mugen",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_mugen_admin_permission_type_status"),
        table_name="admin_permission_type",
        schema="mugen",
    )
    op.drop_column("admin_permission_type", "status", schema="mugen")

    op.drop_index(
        op.f("ix_mugen_admin_permission_object_status"),
        table_name="admin_permission_object",
        schema="mugen",
    )
    op.drop_column("admin_permission_object", "status", schema="mugen")

    op.drop_index(
        op.f("ix_mugen_admin_role_status"),
        table_name="admin_role",
        schema="mugen",
    )
    op.drop_column("admin_role", "status", schema="mugen")

    permission_type_status = postgresql.ENUM(
        "active",
        "deprecated",
        name="admin_permission_type_status",
        schema="mugen",
        create_type=False,
    )
    permission_object_status = postgresql.ENUM(
        "active",
        "deprecated",
        name="admin_permission_object_status",
        schema="mugen",
        create_type=False,
    )
    role_status = postgresql.ENUM(
        "active",
        "deprecated",
        name="admin_role_status",
        schema="mugen",
        create_type=False,
    )

    permission_type_status.drop(op.get_bind(), checkfirst=True)
    permission_object_status.drop(op.get_bind(), checkfirst=True)
    role_status.drop(op.get_bind(), checkfirst=True)
