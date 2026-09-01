"""add governed Knowledge Pack index projections

Revision ID: c4e8a2f6b1d9
Revises: 5b9d2f7a3c1e
Create Date: 2026-09-01 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.schema_contract import resolve_runtime_schema
from migrations.schema_contract import rewrite_mugen_schema_sql

# pylint: disable=no-member

revision: str = "c4e8a2f6b1d9"
down_revision: Union[str, Sequence[str], None] = "5b9d2f7a3c1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def upgrade() -> None:
    """Create the durable tenant-scoped projection queue/status table."""
    projection_status = postgresql.ENUM(
        "queued",
        "processing",
        "ready",
        "failed",
        "cancelled",
        name="knowledge_pack_projection_status",
        schema=_SCHEMA,
        create_type=False,
    )
    projection_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "knowledge_pack_knowledge_index_projection",
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
        sa.Column("knowledge_pack_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_pack_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("target_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("content_checksum", sa.String(length=64), nullable=False),
        sa.Column("projection_schema_version", sa.BigInteger(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            projection_status,
            server_default=_sql_text(
                "'queued'::mugen.knowledge_pack_projection_status"
            ),
            nullable=False,
        ),
        sa.Column(
            "document_count",
            sa.BigInteger(),
            server_default=_sql_text("0"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.BigInteger(),
            server_default=_sql_text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.BigInteger(),
            server_default=_sql_text("3"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=128), nullable=True),
        sa.Column("failure_detail", sa.String(length=1024), nullable=True),
        sa.Column(
            "is_current_ready",
            sa.Boolean(),
            server_default=_sql_text("false"),
            nullable=False,
        ),
        sa.Column(
            "request_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_knowledge_index_projection__tenant_id",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            [f"{_SCHEMA}.admin_user.id"],
            ondelete="SET NULL",
            name="fk_knowledge_index_projection__requested_by_user_id",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_id"),
            (
                f"{_SCHEMA}.knowledge_pack_knowledge_pack.tenant_id",
                f"{_SCHEMA}.knowledge_pack_knowledge_pack.id",
            ),
            name="fkx_knowledge_index_projection__tenant_pack",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id", "knowledge_pack_version_id"),
            (
                f"{_SCHEMA}.knowledge_pack_knowledge_pack_version.tenant_id",
                f"{_SCHEMA}.knowledge_pack_knowledge_pack_version.id",
            ),
            name="fkx_knowledge_index_projection__tenant_version",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "operation IN ('publish', 'reindex', 'rollback', 'cleanup')",
            name="ck_knowledge_index_projection__operation",
        ),
        sa.CheckConstraint(
            "projection_schema_version > 0",
            name="ck_knowledge_index_projection__schema_version_positive",
        ),
        sa.CheckConstraint(
            "document_count >= 0 AND attempt_count >= 0 AND max_attempts > 0",
            name="ck_knowledge_index_projection__counts_nonnegative",
        ),
        sa.CheckConstraint(
            "length(target_fingerprint) = 64 AND length(content_checksum) = 64",
            name="ck_knowledge_index_projection__checksums",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_index_projection"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_knowledge_index_projection__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_index_projection__tenant_version_target",
        "knowledge_pack_knowledge_index_projection",
        [
            "tenant_id",
            "knowledge_pack_version_id",
            "provider",
            "target_fingerprint",
        ],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_knowledge_index_projection__queue_lease",
        "knowledge_pack_knowledge_index_projection",
        ["status", "lease_expires_at", "requested_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_knowledge_index_projection__active_attempt",
        "knowledge_pack_knowledge_index_projection",
        [
            "tenant_id",
            "knowledge_pack_version_id",
            "provider",
            "target_fingerprint",
        ],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'processing')"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_knowledge_index_projection__current_ready",
        "knowledge_pack_knowledge_index_projection",
        [
            "tenant_id",
            "knowledge_pack_version_id",
            "provider",
            "target_fingerprint",
        ],
        unique=True,
        postgresql_where=sa.text("is_current_ready"),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Remove the projection table and its dedicated status type."""
    op.drop_index(
        "ux_knowledge_index_projection__current_ready",
        table_name="knowledge_pack_knowledge_index_projection",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_knowledge_index_projection__active_attempt",
        table_name="knowledge_pack_knowledge_index_projection",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_knowledge_index_projection__queue_lease",
        table_name="knowledge_pack_knowledge_index_projection",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_knowledge_index_projection__tenant_version_target",
        table_name="knowledge_pack_knowledge_index_projection",
        schema=_SCHEMA,
    )
    op.drop_table(
        "knowledge_pack_knowledge_index_projection",
        schema=_SCHEMA,
    )
    postgresql.ENUM(
        "queued",
        "processing",
        "ready",
        "failed",
        "cancelled",
        name="knowledge_pack_projection_status",
        schema=_SCHEMA,
    ).drop(op.get_bind(), checkfirst=True)
