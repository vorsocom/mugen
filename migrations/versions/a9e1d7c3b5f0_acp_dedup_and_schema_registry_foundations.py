"""acp dedup and schema registry foundations

Revision ID: a9e1d7c3b5f0
Revises: f4c9b2d1e6a7
Create Date: 2026-02-25 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "a9e1d7c3b5f0"
down_revision: Union[str, Sequence[str], None] = "f4c9b2d1e6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    dedup_status_enum = postgresql.ENUM(
        "in_progress",
        "succeeded",
        "failed",
        name="admin_dedup_record_status",
        schema=_SCHEMA,
        create_type=False,
    )
    schema_definition_status_enum = postgresql.ENUM(
        "draft",
        "active",
        "inactive",
        name="admin_schema_definition_status",
        schema=_SCHEMA,
        create_type=False,
    )
    dedup_status_enum.create(op.get_bind(), checkfirst=True)
    schema_definition_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "admin_dedup_record",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("scope", postgresql.CITEXT(length=200), nullable=False),
        sa.Column("idempotency_key", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("request_hash", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "status",
            dedup_status_enum,
            server_default=sa.text("'in_progress'"),
            nullable=False,
        ),
        sa.Column("result_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column(
            "response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_code", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("error_message", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column("owner_instance", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_admin_dedup_record__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(scope)) > 0",
            name="ck_dedup_record__scope_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(idempotency_key)) > 0",
            name="ck_dedup_record__idempotency_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_dedup_record"),
        sa.UniqueConstraint(
            "tenant_id",
            "scope",
            "idempotency_key",
            name="ux_dedup_record__tenant_scope_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_dedup_record_tenant_id"),
        "admin_dedup_record",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_dedup_record_status"),
        "admin_dedup_record",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_dedup_record_expires_at"),
        "admin_dedup_record",
        ["expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_dedup_record__tenant_scope_expires",
        "admin_dedup_record",
        ["tenant_id", "scope", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_dedup_record__status_lease_expires",
        "admin_dedup_record",
        ["status", "lease_expires_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "admin_schema_definition",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("description", postgresql.CITEXT(length=2048), nullable=True),
        sa.Column(
            "schema_kind",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'json_schema'"),
            nullable=False,
        ),
        sa.Column(
            "schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "status",
            schema_definition_status_enum,
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("checksum_sha256", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_admin_schema_definition__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["activated_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_admin_schema_definition__activated_by_user_id__admin_user",
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_schema_definition__key_nonempty",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_schema_definition__version_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_schema_definition"),
        sa.UniqueConstraint(
            "tenant_id",
            "key",
            "version",
            name="ux_schema_definition__tenant_key_version",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_schema_definition_tenant_id"),
        "admin_schema_definition",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_schema_definition_key"),
        "admin_schema_definition",
        ["key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_schema_definition_status"),
        "admin_schema_definition",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "admin_schema_binding",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
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
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("schema_definition_id", sa.Uuid(), nullable=False),
        sa.Column("target_namespace", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("target_entity_set", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("target_action", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("binding_kind", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "is_required",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_admin_schema_binding__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["schema_definition_id"],
            [f"{_SCHEMA}.admin_schema_definition.id"],
            ondelete="CASCADE",
            name="fk_admin_schema_binding__schema_definition_id__schema_def",
        ),
        sa.CheckConstraint(
            "length(btrim(target_namespace)) > 0",
            name="ck_schema_binding__target_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(target_entity_set)) > 0",
            name="ck_schema_binding__target_entity_set_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(binding_kind)) > 0",
            name="ck_schema_binding__binding_kind_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_schema_binding"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_schema_binding_tenant_id"),
        "admin_schema_binding",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_schema_binding_schema_definition_id"),
        "admin_schema_binding",
        ["schema_definition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_schema_binding_is_active"),
        "admin_schema_binding",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_mugen_admin_schema_binding_is_active"),
        table_name="admin_schema_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_schema_binding_schema_definition_id"),
        table_name="admin_schema_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_schema_binding_tenant_id"),
        table_name="admin_schema_binding",
        schema=_SCHEMA,
    )
    op.drop_table("admin_schema_binding", schema=_SCHEMA)

    op.drop_index(
        op.f("ix_mugen_admin_schema_definition_status"),
        table_name="admin_schema_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_schema_definition_key"),
        table_name="admin_schema_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_schema_definition_tenant_id"),
        table_name="admin_schema_definition",
        schema=_SCHEMA,
    )
    op.drop_table("admin_schema_definition", schema=_SCHEMA)

    op.drop_index(
        "ix_dedup_record__status_lease_expires",
        table_name="admin_dedup_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_dedup_record__tenant_scope_expires",
        table_name="admin_dedup_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_dedup_record_expires_at"),
        table_name="admin_dedup_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_dedup_record_status"),
        table_name="admin_dedup_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_dedup_record_tenant_id"),
        table_name="admin_dedup_record",
        schema=_SCHEMA,
    )
    op.drop_table("admin_dedup_record", schema=_SCHEMA)

    schema_definition_status_enum = postgresql.ENUM(
        name="admin_schema_definition_status",
        schema=_SCHEMA,
        create_type=False,
    )
    dedup_status_enum = postgresql.ENUM(
        name="admin_dedup_record_status",
        schema=_SCHEMA,
        create_type=False,
    )
    schema_definition_status_enum.drop(op.get_bind(), checkfirst=True)
    dedup_status_enum.drop(op.get_bind(), checkfirst=True)
