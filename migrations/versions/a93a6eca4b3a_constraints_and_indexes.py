"""Ensure constraints and indexes.

Revision ID: a93a6eca4b3a
Revises: ed33a7c861dd
Create Date: 2025-12-16 09:51:36.304720

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a93a6eca4b3a"
down_revision: Union[str, Sequence[str], None] = "ed33a7c861dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# pylint: disable=no-member
def upgrade() -> None:
    """Upgrade schema."""
    # GlobalPermissionEntry.
    op.create_index(
        "ix_global_permission_entry__object_type_role_permitted",
        "admin_global_permission_entry",
        ["global_role_id", "permission_object_id", "permission_type_id"],
        postgresql_where=sa.text("permitted IS TRUE"),
        schema="mugen",
    )

    # GlobalRole.

    # GlobalRoleMembership.

    # PermissionEntry.
    op.create_index(
        "ix_permission_entry__object_tenant_type_role_permitted",
        "admin_permission_entry",
        ["tenant_id", "role_id", "permission_object_id", "permission_type_id"],
        postgresql_where=sa.text("permitted IS TRUE"),
        schema="mugen",
    )

    # PermissionObject.

    # PermissionType.

    # Person.

    # RefreshToken.

    # Role.

    # RoleMembership.

    # SystemFlag.

    # Tenant.
    # Allow one active tenant per slug.
    op.create_index(
        "ux_tenant__slug_active",
        "admin_tenant",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        schema="mugen",
    )

    # TenantDomain.
    # Allow only one primary domain per tenant.
    op.create_index(
        "ux_tenant_domain__domain_primary",
        "admin_tenant_domain",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_primary IS TRUE"),
        schema="mugen",
    )

    # TenantInvitation.
    # Allow only ONE pending invitation per tenant per email.
    op.create_index(
        "ux_tenant_invitation__email_pending",
        "admin_tenant_invitation",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'invited' AND accepted_at IS NULL"),
        schema="mugen",
    )

    # TenantMembership.

    # User.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_global_permission_entry__object_type_role_permitted",
        table_name="admin_global_permission_entry",
        schema="mugen",
    )
    op.drop_index(
        "ix_permission_entry__object_tenant_type_role_permitted",
        table_name="admin_permission_entry",
        schema="mugen",
    )
    op.drop_index(
        "ux_tenant__slug_active",
        table_name="admin_tenant",
        schema="mugen",
    )
    op.drop_index(
        "ux_tenant_domain__domain_primary",
        table_name="admin_tenant_domain",
        schema="mugen",
    )
    op.drop_index(
        "ux_tenant_invitation__email_pending",
        table_name="admin_tenant_invitation",
        schema="mugen",
    )
