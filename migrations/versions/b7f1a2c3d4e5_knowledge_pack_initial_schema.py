"""knowledge_pack initial schema

Revision ID: b7f1a2c3d4e5
Revises: a8c3b1d4e5f6
Create Date: 2026-02-13 19:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "b7f1a2c3d4e5"
down_revision: Union[str, None] = "a8c3b1d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    knowledge_pack_publication_status = postgresql.ENUM(
        "draft",
        "review",
        "approved",
        "published",
        "archived",
        name="knowledge_pack_publication_status",
        schema=_SCHEMA,
        create_type=False,
    )
    knowledge_pack_approval_action = postgresql.ENUM(
        "submit_for_review",
        "approve",
        "reject",
        "publish",
        "archive",
        "rollback_version",
        name="knowledge_pack_approval_action",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    knowledge_pack_publication_status.create(bind, checkfirst=True)
    knowledge_pack_approval_action.create(bind, checkfirst=True)

    op.create_table(
        "knowledge_pack_knowledge_pack",
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
        sa.Column("name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_pack_pack__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_knowledge_pack_pack__key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_knowledge_pack_pack__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_knowledge_pack_pack__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_pack_pack"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_pack_pack__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "key",
            name="ux_knowledge_pack_pack__tenant_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_pack_pack__tenant_active",
        "knowledge_pack_knowledge_pack",
        ["tenant_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "knowledge_pack_knowledge_pack_version",
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
        sa.Column("knowledge_pack_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            knowledge_pack_publication_status,
            server_default=sa.text("'draft'::mugen.knowledge_pack_publication_status"),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("rollback_of_version_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=2048), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_pack_version__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_pack_version__submitted_by__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_pack_version__approved_by__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_pack_version__published_by__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_pack_version__archived_by__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["rollback_of_version_id"],
            ["mugen.knowledge_pack_knowledge_pack_version.id"],
            ondelete="SET NULL",
            name="fk_knowledge_pack_version__rollback_of_version_id",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_id"),
            (
                "mugen.knowledge_pack_knowledge_pack.tenant_id",
                "mugen.knowledge_pack_knowledge_pack.id",
            ),
            name="fkx_knowledge_pack_version__tenant_pack",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_knowledge_pack_version__version_number_positive",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_knowledge_pack_version__note_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_pack_version"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_pack_version__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "knowledge_pack_id",
            "version_number",
            name="ux_knowledge_pack_version__tenant_pack_version",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_pack_version__tenant_pack_status",
        "knowledge_pack_knowledge_pack_version",
        ["tenant_id", "knowledge_pack_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_foreign_key(
        "fk_knowledge_pack_pack__current_version_id",
        source_table="knowledge_pack_knowledge_pack",
        referent_table="knowledge_pack_knowledge_pack_version",
        local_cols=["current_version_id"],
        remote_cols=["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )

    op.create_table(
        "knowledge_pack_knowledge_entry",
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
        sa.Column("knowledge_pack_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_pack_version_id", sa.Uuid(), nullable=False),
        sa.Column("entry_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("title", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("summary", sa.String(length=2048), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_entry__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_id"),
            (
                "mugen.knowledge_pack_knowledge_pack.tenant_id",
                "mugen.knowledge_pack_knowledge_pack.id",
            ),
            name="fkx_knowledge_entry__tenant_pack",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                "mugen.knowledge_pack_knowledge_pack_version.tenant_id",
                "mugen.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_entry__tenant_pack_version",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(btrim(entry_key)) > 0",
            name="ck_knowledge_entry__entry_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(title)) > 0",
            name="ck_knowledge_entry__title_nonempty",
        ),
        sa.CheckConstraint(
            "summary IS NULL OR length(btrim(summary)) > 0",
            name="ck_knowledge_entry__summary_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_entry"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_entry__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "knowledge_pack_version_id",
            "entry_key",
            name="ux_knowledge_entry__tenant_version_entry_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_entry__tenant_version_active",
        "knowledge_pack_knowledge_entry",
        ["tenant_id", "knowledge_pack_version_id", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "knowledge_pack_knowledge_entry_revision",
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
        sa.Column("knowledge_entry_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_pack_version_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            knowledge_pack_publication_status,
            server_default=sa.text("'draft'::mugen.knowledge_pack_publication_status"),
            nullable=False,
        ),
        sa.Column("body", sa.String(length=8192), nullable=True),
        sa.Column("body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("channel", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("locale", postgresql.CITEXT(length=16), nullable=True),
        sa.Column("category", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_entry_revision__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_entry_revision__published_by__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_entry_revision__archived_by__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_entry_id"),
            (
                "mugen.knowledge_pack_knowledge_entry.tenant_id",
                "mugen.knowledge_pack_knowledge_entry.id",
            ),
            name="fkx_knowledge_entry_revision__tenant_entry",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                "mugen.knowledge_pack_knowledge_pack_version.tenant_id",
                "mugen.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_entry_revision__tenant_pack_version",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "revision_number > 0",
            name="ck_knowledge_entry_revision__revision_number_positive",
        ),
        sa.CheckConstraint(
            "body IS NOT NULL OR body_json IS NOT NULL",
            name="ck_knowledge_entry_revision__content_required",
        ),
        sa.CheckConstraint(
            "body IS NULL OR length(btrim(body)) > 0",
            name="ck_knowledge_entry_revision__body_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "channel IS NULL OR length(btrim(channel)) > 0",
            name="ck_knowledge_entry_revision__channel_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "locale IS NULL OR length(btrim(locale)) > 0",
            name="ck_knowledge_entry_revision__locale_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "category IS NULL OR length(btrim(category)) > 0",
            name="ck_knowledge_entry_revision__category_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_entry_revision"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_entry_revision__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "knowledge_entry_id",
            "revision_number",
            name="ux_knowledge_entry_revision__tenant_entry_revision",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_entry_revision__tenant_version_status",
        "knowledge_pack_knowledge_entry_revision",
        ["tenant_id", "knowledge_pack_version_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_entry_revision__tenant_scope_status",
        "knowledge_pack_knowledge_entry_revision",
        ["tenant_id", "channel", "locale", "category", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "knowledge_pack_knowledge_approval",
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
        sa.Column("knowledge_pack_version_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_entry_revision_id", sa.Uuid(), nullable=True),
        sa.Column("action", knowledge_pack_approval_action, nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("note", sa.String(length=2048), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_approval__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_approval__actor_user_id__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                "mugen.knowledge_pack_knowledge_pack_version.tenant_id",
                "mugen.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_approval__tenant_pack_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_entry_revision_id"),
            (
                "mugen.knowledge_pack_knowledge_entry_revision.tenant_id",
                "mugen.knowledge_pack_knowledge_entry_revision.id",
            ),
            name="fkx_knowledge_approval__tenant_entry_revision",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(btrim(note)) > 0",
            name="ck_knowledge_approval__note_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_approval"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_approval__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_approval__tenant_version_occurred",
        "knowledge_pack_knowledge_approval",
        ["tenant_id", "knowledge_pack_version_id", "occurred_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "knowledge_pack_knowledge_scope",
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
        sa.Column("knowledge_pack_version_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_entry_revision_id", sa.Uuid(), nullable=False),
        sa.Column("channel", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("locale", postgresql.CITEXT(length=16), nullable=True),
        sa.Column("category", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_scope__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                "mugen.knowledge_pack_knowledge_pack_version.tenant_id",
                "mugen.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_scope__tenant_pack_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_entry_revision_id"),
            (
                "mugen.knowledge_pack_knowledge_entry_revision.tenant_id",
                "mugen.knowledge_pack_knowledge_entry_revision.id",
            ),
            name="fkx_knowledge_scope__tenant_entry_revision",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "channel IS NULL OR length(btrim(channel)) > 0",
            name="ck_knowledge_scope__channel_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "locale IS NULL OR length(btrim(locale)) > 0",
            name="ck_knowledge_scope__locale_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "category IS NULL OR length(btrim(category)) > 0",
            name="ck_knowledge_scope__category_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_scope"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_scope__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_scope__tenant_scope_active",
        "knowledge_pack_knowledge_scope",
        ["tenant_id", "channel", "locale", "category", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_scope__tenant_scope_active",
        table_name="knowledge_pack_knowledge_scope",
        schema=_SCHEMA,
    )
    op.drop_table("knowledge_pack_knowledge_scope", schema=_SCHEMA)

    op.drop_index(
        "ix_knowledge_approval__tenant_version_occurred",
        table_name="knowledge_pack_knowledge_approval",
        schema=_SCHEMA,
    )
    op.drop_table("knowledge_pack_knowledge_approval", schema=_SCHEMA)

    op.drop_index(
        "ix_knowledge_entry_revision__tenant_scope_status",
        table_name="knowledge_pack_knowledge_entry_revision",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_knowledge_entry_revision__tenant_version_status",
        table_name="knowledge_pack_knowledge_entry_revision",
        schema=_SCHEMA,
    )
    op.drop_table("knowledge_pack_knowledge_entry_revision", schema=_SCHEMA)

    op.drop_index(
        "ix_knowledge_entry__tenant_version_active",
        table_name="knowledge_pack_knowledge_entry",
        schema=_SCHEMA,
    )
    op.drop_table("knowledge_pack_knowledge_entry", schema=_SCHEMA)

    op.drop_constraint(
        "fk_knowledge_pack_pack__current_version_id",
        table_name="knowledge_pack_knowledge_pack",
        schema=_SCHEMA,
        type_="foreignkey",
    )

    op.drop_index(
        "ix_knowledge_pack_version__tenant_pack_status",
        table_name="knowledge_pack_knowledge_pack_version",
        schema=_SCHEMA,
    )
    op.drop_table("knowledge_pack_knowledge_pack_version", schema=_SCHEMA)

    op.drop_index(
        "ix_knowledge_pack_pack__tenant_active",
        table_name="knowledge_pack_knowledge_pack",
        schema=_SCHEMA,
    )
    op.drop_table("knowledge_pack_knowledge_pack", schema=_SCHEMA)

    postgresql.ENUM(
        "submit_for_review",
        "approve",
        "reject",
        "publish",
        "archive",
        "rollback_version",
        name="knowledge_pack_approval_action",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(
        "draft",
        "review",
        "approved",
        "published",
        "archived",
        name="knowledge_pack_publication_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
