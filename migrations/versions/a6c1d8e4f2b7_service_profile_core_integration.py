"""add Core Service Profile routing and Subscription scope

Revision ID: a6c1d8e4f2b7
Revises: c4e8a2f6b1d9
Create Date: 2026-09-01 15:00:00.000000

"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

from migrations.schema_contract import resolve_runtime_schema, rewrite_mugen_schema_sql

# pylint: disable=no-member

revision: str = "a6c1d8e4f2b7"
down_revision: Union[str, Sequence[str], None] = "c4e8a2f6b1d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_LOG = logging.getLogger(__name__)


def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def _identity_columns() -> list[sa.Column]:
    return [
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
    ]


def _tenant_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        [f"{_SCHEMA}.admin_tenant.id"],
        ondelete="RESTRICT",
        name=name,
    )


def _deleted_actor_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["deleted_by_user_id"],
        [f"{_SCHEMA}.admin_user.id"],
        name=name,
    )


def _reseed_acp_manifest() -> None:
    if context.is_offline_mode():
        _LOG.warning("Skipping ACP reseed in offline mode.")
        return
    mugen_cfg = context.config.attributes.get("mugen_cfg")
    if not mugen_cfg:
        raise RuntimeError("mugen_cfg was not provided to Alembic env.")
    if not bool(mugen_cfg.get("acp", {}).get("seed_acp", False)):
        _LOG.warning("ACP reseed skipped by config.")
        return

    from mugen.core.plugin.acp.migration.apply_manifest import apply_manifest
    from mugen.core.plugin.acp.migration.loader import contribute_all
    from mugen.core.plugin.acp.sdk.registry import AdminRegistry

    registry = AdminRegistry(strict_permission_decls=True)
    contribute_all(registry, mugen_cfg=mugen_cfg)
    apply_manifest(
        op.get_bind(),
        registry.build_seed_manifest(),
        schema=_SCHEMA,
    )


def upgrade() -> None:
    """Create Service Profile resources and Knowledge Scope integration."""
    lifecycle_status = postgresql.ENUM(
        "draft",
        "active",
        "disabled",
        name="service_profile_lifecycle_status",
        schema=_SCHEMA,
        create_type=False,
    )
    lifecycle_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "service_profile_service_profile",
        *_identity_columns(),
        sa.Column("key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=256), nullable=False),
        sa.Column(
            "status",
            lifecycle_status,
            server_default=_sql_text("'draft'::mugen.service_profile_lifecycle_status"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        _tenant_fk("fk_service_profile__tenant_id"),
        _deleted_actor_fk("fk_service_profile__deleted_by_user_id"),
        sa.CheckConstraint(
            "length(btrim(key)) > 0 AND key = btrim(key) AND key = lower(key)",
            name="ck_service_profile__key_nonempty_trimmed",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name = btrim(display_name)",
            name="ck_service_profile__display_name_nonempty_trimmed",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND activated_at IS NULL AND disabled_at IS NULL) OR "
            "(status = 'active' AND activated_at IS NOT NULL AND disabled_at IS NULL) "
            "OR (status = 'disabled' AND activated_at IS NOT NULL AND "
            "disabled_at IS NOT NULL)",
            name="ck_service_profile__lifecycle_timestamps",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_service_profile__archive_actor",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_profile"),
        sa.UniqueConstraint("tenant_id", "id", name="ux_service_profile__tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "key", name="ux_service_profile__tenant_key"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_service_profile__tenant_status_deleted",
        "service_profile_service_profile",
        ["tenant_id", "status", "deleted_at"],
        schema=_SCHEMA,
    )

    op.create_table(
        "service_profile_ingress_binding",
        *_identity_columns(),
        sa.Column("service_profile_id", sa.Uuid(), nullable=False),
        sa.Column("ingress_binding_id", sa.Uuid(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=_sql_text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _tenant_fk("fk_service_profile_ingress__tenant_id"),
        sa.ForeignKeyConstraint(
            ("tenant_id", "service_profile_id"),
            (
                f"{_SCHEMA}.service_profile_service_profile.tenant_id",
                f"{_SCHEMA}.service_profile_service_profile.id",
            ),
            name="fkx_service_profile_ingress__tenant_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "ingress_binding_id"),
            (
                f"{_SCHEMA}.channel_orchestration_ingress_binding.tenant_id",
                f"{_SCHEMA}.channel_orchestration_ingress_binding.id",
            ),
            name="fkx_service_profile_ingress__tenant_binding",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_profile_ingress"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_service_profile_ingress__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "service_profile_id",
            "ingress_binding_id",
            name="ux_service_profile_ingress__tenant_profile_binding",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_service_profile_ingress__active_binding",
        "service_profile_ingress_binding",
        ["tenant_id", "ingress_binding_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_service_profile_ingress__tenant_profile_active",
        "service_profile_ingress_binding",
        ["tenant_id", "service_profile_id", "is_active"],
        schema=_SCHEMA,
    )

    op.create_table(
        "service_profile_subscription",
        *_identity_columns(),
        sa.Column("service_profile_id", sa.Uuid(), nullable=False),
        sa.Column("billing_subscription_id", sa.Uuid(), nullable=False),
        sa.Column("product_code", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "status",
            lifecycle_status,
            server_default=_sql_text("'draft'::mugen.service_profile_lifecycle_status"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by_user_id", sa.Uuid(), nullable=True),
        _tenant_fk("fk_service_profile_subscription__tenant_id"),
        _deleted_actor_fk("fk_service_profile_subscription__deleted_by_user_id"),
        sa.ForeignKeyConstraint(
            ("tenant_id", "service_profile_id"),
            (
                f"{_SCHEMA}.service_profile_service_profile.tenant_id",
                f"{_SCHEMA}.service_profile_service_profile.id",
            ),
            name="fkx_service_profile_subscription__tenant_profile",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "billing_subscription_id"),
            (
                f"{_SCHEMA}.billing_subscription.tenant_id",
                f"{_SCHEMA}.billing_subscription.id",
            ),
            name="fkx_service_profile_subscription__tenant_subscription",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "product_code IS NULL OR (length(btrim(product_code)) > 0 AND "
            "product_code = btrim(product_code) AND product_code = "
            "lower(product_code))",
            name="ck_service_profile_subscription__product_code",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND product_code IS NULL AND activated_at IS NULL "
            "AND disabled_at IS NULL) OR (status = 'active' AND "
            "product_code IS NOT NULL AND activated_at IS NOT NULL AND "
            "disabled_at IS NULL) OR (status = 'disabled' AND "
            "product_code IS NOT NULL AND activated_at IS NOT NULL AND "
            "disabled_at IS NOT NULL)",
            name="ck_service_profile_subscription__lifecycle",
        ),
        sa.CheckConstraint(
            "NOT (deleted_at IS NOT NULL AND deleted_by_user_id IS NULL)",
            name="ck_service_profile_subscription__archive_actor",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_profile_subscription"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_service_profile_subscription__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    active_assignment = sa.text("status = 'active' AND deleted_at IS NULL")
    op.create_index(
        "ux_service_profile_subscription__active_subscription",
        "service_profile_subscription",
        ["tenant_id", "billing_subscription_id"],
        unique=True,
        postgresql_where=active_assignment,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_service_profile_subscription__active_profile_product",
        "service_profile_subscription",
        ["tenant_id", "service_profile_id", "product_code"],
        unique=True,
        postgresql_where=active_assignment,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_service_profile_subscription__tenant_status_deleted",
        "service_profile_subscription",
        ["tenant_id", "status", "deleted_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_service_profile_subscription__tenant_profile_status",
        "service_profile_subscription",
        ["tenant_id", "service_profile_id", "status"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_service_profile_subscription__tenant_product",
        "service_profile_subscription",
        ["tenant_id", "product_code"],
        schema=_SCHEMA,
    )

    op.add_column(
        "knowledge_pack_knowledge_scope",
        sa.Column("service_profile_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fkx_knowledge_scope__tenant_service_profile",
        "knowledge_pack_knowledge_scope",
        "service_profile_service_profile",
        ["tenant_id", "service_profile_id"],
        ["tenant_id", "id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_knowledge_scope__tenant_service_profile_active",
        "knowledge_pack_knowledge_scope",
        ["tenant_id", "service_profile_id", "is_active"],
        schema=_SCHEMA,
    )
    _reseed_acp_manifest()


def downgrade() -> None:
    """Remove Service Profile integration without changing referenced records."""
    op.drop_index(
        "ix_knowledge_scope__tenant_service_profile_active",
        table_name="knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "fkx_knowledge_scope__tenant_service_profile",
        "knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column(
        "knowledge_pack_knowledge_scope",
        "service_profile_id",
        schema=_SCHEMA,
    )
    op.drop_table("service_profile_subscription", schema=_SCHEMA)
    op.drop_table("service_profile_ingress_binding", schema=_SCHEMA)
    op.drop_table("service_profile_service_profile", schema=_SCHEMA)
    postgresql.ENUM(
        "draft",
        "active",
        "disabled",
        name="service_profile_lifecycle_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
