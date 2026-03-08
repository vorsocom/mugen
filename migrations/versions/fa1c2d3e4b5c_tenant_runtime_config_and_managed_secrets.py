"""Tenant runtime config overlays and managed ACP secret material.

Revision ID: fa1c2d3e4b5c
Revises: 6d5f8a2c1b3e
Create Date: 2026-03-08 22:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from migrations.schema_contract import rewrite_mugen_schema_sql
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fa1c2d3e4b5c"
down_revision: Union[str, Sequence[str], None] = "6d5f8a2c1b3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def upgrade() -> None:
    op.add_column(
        "admin_key_ref",
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "admin_key_ref",
        sa.Column(
            "has_material",
            sa.Boolean(),
            server_default=_sql_text("false"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "admin_key_ref",
        sa.Column("material_last_set_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "admin_key_ref",
        sa.Column("material_last_set_by_user_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_has_material"),
        "admin_key_ref",
        ["has_material"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_material_last_set_by_user_id"),
        "admin_key_ref",
        ["material_last_set_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "admin_runtime_config_profile",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=_sql_text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=_sql_text("1"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=_sql_text("true"),
            nullable=False,
        ),
        sa.Column(
            "settings_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_runtime_cfg_profile_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(category)) > 0",
            name="ck_runtime_cfg_profile__category_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(profile_key)) > 0",
            name="ck_runtime_cfg_profile__profile_key_nonempty",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_runtime_cfg_profile__display_name_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_runtime_config_profile"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_runtime_cfg_profile__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "category",
            "profile_key",
            name="ux_runtime_cfg_profile__tenant_category_profile",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_runtime_config_profile_tenant_id"),
        "admin_runtime_config_profile",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_runtime_config_profile_category"),
        "admin_runtime_config_profile",
        ["category"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_runtime_config_profile_profile_key"),
        "admin_runtime_config_profile",
        ["profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_runtime_config_profile_is_active"),
        "admin_runtime_config_profile",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_runtime_cfg_profile__tenant_category_active",
        "admin_runtime_config_profile",
        ["tenant_id", "category", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_cfg_profile__tenant_category_active",
        table_name="admin_runtime_config_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_runtime_config_profile_is_active"),
        table_name="admin_runtime_config_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_runtime_config_profile_profile_key"),
        table_name="admin_runtime_config_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_runtime_config_profile_category"),
        table_name="admin_runtime_config_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_runtime_config_profile_tenant_id"),
        table_name="admin_runtime_config_profile",
        schema=_SCHEMA,
    )
    op.drop_table("admin_runtime_config_profile", schema=_SCHEMA)

    op.drop_index(
        op.f("ix_mugen_admin_key_ref_material_last_set_by_user_id"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_has_material"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_column("admin_key_ref", "material_last_set_by_user_id", schema=_SCHEMA)
    op.drop_column("admin_key_ref", "material_last_set_at", schema=_SCHEMA)
    op.drop_column("admin_key_ref", "has_material", schema=_SCHEMA)
    op.drop_column("admin_key_ref", "encrypted_secret", schema=_SCHEMA)
