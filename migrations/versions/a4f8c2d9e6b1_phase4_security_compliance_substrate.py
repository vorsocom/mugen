"""phase4 security + compliance substrate

Revision ID: a4f8c2d9e6b1
Revises: d3f5a7b9c1e2
Create Date: 2026-02-25 18:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import rewrite_mugen_schema_sql
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def _execute(statement) -> None:
    if isinstance(statement, str):
        op.execute(_sql(statement))
        return
    op.execute(statement)


# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "a4f8c2d9e6b1"
down_revision: Union[str, None] = "d3f5a7b9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    key_ref_status = postgresql.ENUM(
        "active",
        "retired",
        "destroyed",
        name="admin_key_ref_status",
        schema=_SCHEMA,
        create_type=False,
    )
    key_ref_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "admin_key_ref",
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
        sa.Column("purpose", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("key_id", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "provider",
            postgresql.CITEXT(length=64),
            server_default=_sql_text("'local'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            key_ref_status,
            server_default=_sql_text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("retired_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("destroyed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("destroy_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_admin_key_ref_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(purpose)) > 0",
            name="ck_key_ref__purpose_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(key_id)) > 0",
            name="ck_key_ref__key_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(provider)) > 0",
            name="ck_key_ref__provider_nonempty",
        ),
        sa.CheckConstraint(
            "retired_reason IS NULL OR length(btrim(retired_reason)) > 0",
            name="ck_key_ref__retired_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "destroy_reason IS NULL OR length(btrim(destroy_reason)) > 0",
            name="ck_key_ref__destroy_reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_key_ref"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_key_ref__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "purpose",
            "key_id",
            name="ux_key_ref__tenant_purpose_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_tenant_id"),
        "admin_key_ref",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_purpose"),
        "admin_key_ref",
        ["purpose"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_key_id"),
        "admin_key_ref",
        ["key_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_status"),
        "admin_key_ref",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_retired_at"),
        "admin_key_ref",
        ["retired_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_retired_by_user_id"),
        "admin_key_ref",
        ["retired_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_destroyed_at"),
        "admin_key_ref",
        ["destroyed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_key_ref_destroyed_by_user_id"),
        "admin_key_ref",
        ["destroyed_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_key_ref__tenant_purpose_status",
        "admin_key_ref",
        ["tenant_id", "purpose", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_key_ref__tenant_purpose_active",
        "admin_key_ref",
        ["tenant_id", "purpose"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("status = 'active'"),
    )

    op.create_table(
        "admin_plugin_capability_grant",
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
        sa.Column("plugin_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_sql_text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_admin_plugin_capability_grant_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(plugin_key)) > 0",
            name="ck_plugin_capability_grant__plugin_key_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capabilities) = 'array'",
            name="ck_plugin_capability_grant__capabilities_is_array",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(capabilities) > 0",
            name="ck_plugin_capability_grant__capabilities_nonempty",
        ),
        sa.CheckConstraint(
            "revoke_reason IS NULL OR length(btrim(revoke_reason)) > 0",
            name="ck_plugin_capability_grant__revoke_reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_admin_plugin_capability_grant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_plugin_capability_grant__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_tenant_id"),
        "admin_plugin_capability_grant",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_plugin_key"),
        "admin_plugin_capability_grant",
        ["plugin_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_granted_at"),
        "admin_plugin_capability_grant",
        ["granted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_granted_by_user_id"),
        "admin_plugin_capability_grant",
        ["granted_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_expires_at"),
        "admin_plugin_capability_grant",
        ["expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_revoked_at"),
        "admin_plugin_capability_grant",
        ["revoked_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_admin_plugin_capability_grant_revoked_by_user_id"),
        "admin_plugin_capability_grant",
        ["revoked_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_plugin_capability_grant__tenant_plugin",
        "admin_plugin_capability_grant",
        ["tenant_id", "plugin_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_plugin_capability_grant__tenant_plugin_active",
        "admin_plugin_capability_grant",
        ["tenant_id", "plugin_key"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("revoked_at IS NULL"),
    )

    op.create_table(
        "audit_evidence_blob",
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
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("source_plugin", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("subject_namespace", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("storage_uri", postgresql.CITEXT(length=512), nullable=False),
        sa.Column("content_hash", postgresql.CITEXT(length=128), nullable=False),
        sa.Column(
            "hash_alg",
            postgresql.CITEXT(length=32),
            server_default=_sql_text("'sha256'"),
            nullable=False,
        ),
        sa.Column("content_length", sa.BigInteger(), nullable=True),
        sa.Column(
            "immutability",
            postgresql.CITEXT(length=32),
            server_default=_sql_text("'immutable'"),
            nullable=False,
        ),
        sa.Column(
            "verification_status",
            postgresql.CITEXT(length=32),
            server_default=_sql_text("'pending'"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redaction_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redaction_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("legal_hold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_hold_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_hold_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "legal_hold_reason",
            postgresql.CITEXT(length=255),
            nullable=True,
        ),
        sa.Column("legal_hold_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_hold_released_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "legal_hold_release_reason",
            postgresql.CITEXT(length=255),
            nullable=True,
        ),
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tombstoned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("tombstone_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("purge_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purged_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("purge_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_audit_evidence_blob_tenant",
        ),
        sa.CheckConstraint(
            "trace_id IS NULL OR length(btrim(trace_id)) > 0",
            name="ck_audit_evidence_blob__trace_id_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "source_plugin IS NULL OR length(btrim(source_plugin)) > 0",
            name="ck_audit_evidence_blob__source_plugin_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "subject_namespace IS NULL OR length(btrim(subject_namespace)) > 0",
            name="ck_audit_evidence_blob__subject_namespace_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "length(btrim(storage_uri)) > 0",
            name="ck_audit_evidence_blob__storage_uri_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_audit_evidence_blob__content_hash_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(hash_alg)) > 0",
            name="ck_audit_evidence_blob__hash_alg_nonempty",
        ),
        sa.CheckConstraint(
            "content_length IS NULL OR content_length >= 0",
            name="ck_audit_evidence_blob__content_length_nonnegative",
        ),
        sa.CheckConstraint(
            "immutability IN ('immutable', 'mutable')",
            name="ck_audit_evidence_blob__immutability_valid",
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'failed')",
            name="ck_audit_evidence_blob__verification_status_valid",
        ),
        sa.CheckConstraint(
            "redaction_reason IS NULL OR length(btrim(redaction_reason)) > 0",
            name="ck_audit_evidence_blob__redaction_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "legal_hold_reason IS NULL OR length(btrim(legal_hold_reason)) > 0",
            name="ck_audit_evidence_blob__legal_hold_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "legal_hold_release_reason IS NULL OR"
                " length(btrim(legal_hold_release_reason)) > 0"
            ),
            name="ck_audit_evidence_blob__hold_release_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "tombstone_reason IS NULL OR length(btrim(tombstone_reason)) > 0",
            name="ck_audit_evidence_blob__tombstone_reason_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "purge_reason IS NULL OR length(btrim(purge_reason)) > 0",
            name="ck_audit_evidence_blob__purge_reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_evidence_blob"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_audit_evidence_blob__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_tenant_id"),
        "audit_evidence_blob",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_trace_id"),
        "audit_evidence_blob",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_source_plugin"),
        "audit_evidence_blob",
        ["source_plugin"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_subject_namespace"),
        "audit_evidence_blob",
        ["subject_namespace"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_subject_id"),
        "audit_evidence_blob",
        ["subject_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_content_hash"),
        "audit_evidence_blob",
        ["content_hash"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_verification_status"),
        "audit_evidence_blob",
        ["verification_status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_verified_at"),
        "audit_evidence_blob",
        ["verified_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_verified_by_user_id"),
        "audit_evidence_blob",
        ["verified_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_retention_until"),
        "audit_evidence_blob",
        ["retention_until"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_redaction_due_at"),
        "audit_evidence_blob",
        ["redaction_due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_redacted_at"),
        "audit_evidence_blob",
        ["redacted_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_at"),
        "audit_evidence_blob",
        ["legal_hold_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_by_user_id"),
        "audit_evidence_blob",
        ["legal_hold_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_released_at"),
        "audit_evidence_blob",
        ["legal_hold_released_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_released_by_user_id"),
        "audit_evidence_blob",
        ["legal_hold_released_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_tombstoned_at"),
        "audit_evidence_blob",
        ["tombstoned_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_tombstoned_by_user_id"),
        "audit_evidence_blob",
        ["tombstoned_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_purge_due_at"),
        "audit_evidence_blob",
        ["purge_due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_purged_at"),
        "audit_evidence_blob",
        ["purged_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_evidence_blob_purged_by_user_id"),
        "audit_evidence_blob",
        ["purged_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_evidence_blob__tenant_trace",
        "audit_evidence_blob",
        ["tenant_id", "trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_evidence_blob__tenant_content_hash",
        "audit_evidence_blob",
        ["tenant_id", "content_hash"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_retention_class",
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
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("resource_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "retention_days",
            sa.BigInteger(),
            server_default=_sql_text("0"),
            nullable=False,
        ),
        sa.Column("redaction_after_days", sa.BigInteger(), nullable=True),
        sa.Column(
            "purge_grace_days",
            sa.BigInteger(),
            server_default=_sql_text("30"),
            nullable=False,
        ),
        sa.Column(
            "legal_hold_allowed",
            sa.Boolean(),
            server_default=_sql_text("true"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=_sql_text("true"),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_retention_class_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_gov_retention_class__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_gov_retention_class__name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_gov_retention_class__resource_type_nonempty",
        ),
        sa.CheckConstraint(
            "retention_days >= 0",
            name="ck_ops_gov_retention_class__retention_days_nonnegative",
        ),
        sa.CheckConstraint(
            "redaction_after_days IS NULL OR redaction_after_days >= 0",
            name="ck_ops_gov_retention_class__redaction_days_nonnegative",
        ),
        sa.CheckConstraint(
            "purge_grace_days >= 0",
            name="ck_ops_gov_retention_class__purge_grace_days_nonnegative",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_gov_retention_class__description_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_governance_retention_class"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_retention_class__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_gov_retention_class__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_retention_class_tenant_id"),
        "ops_governance_retention_class",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_retention_class_code"),
        "ops_governance_retention_class",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_retention_class_resource_type"),
        "ops_governance_retention_class",
        ["resource_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_retention_class_is_active"),
        "ops_governance_retention_class",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_class__tenant_resource_active",
        "ops_governance_retention_class",
        ["tenant_id", "resource_type", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_legal_hold",
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
        sa.Column("retention_class_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("reason", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("hold_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            server_default=_sql_text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "placed_at",
            sa.DateTime(timezone=True),
            server_default=_sql_text("now()"),
            nullable=False,
        ),
        sa.Column("placed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("release_reason", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ("tenant_id", "retention_class_id"),
            (
                f"{_SCHEMA}.ops_governance_retention_class.tenant_id",
                f"{_SCHEMA}.ops_governance_retention_class.id",
            ),
            name="fkx_ops_gov_legal_hold__tenant_retention_class",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_gov_legal_hold__resource_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0",
            name="ck_ops_gov_legal_hold__reason_nonempty",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_ops_gov_legal_hold__status_valid",
        ),
        sa.CheckConstraint(
            "release_reason IS NULL OR length(btrim(release_reason)) > 0",
            name="ck_ops_gov_legal_hold__release_reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_governance_legal_hold"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_legal_hold__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_tenant_id"),
        "ops_governance_legal_hold",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_retention_class_id"),
        "ops_governance_legal_hold",
        ["retention_class_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_resource_type"),
        "ops_governance_legal_hold",
        ["resource_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_resource_id"),
        "ops_governance_legal_hold",
        ["resource_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_status"),
        "ops_governance_legal_hold",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_placed_at"),
        "ops_governance_legal_hold",
        ["placed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_placed_by_user_id"),
        "ops_governance_legal_hold",
        ["placed_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_released_at"),
        "ops_governance_legal_hold",
        ["released_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_legal_hold_released_by_user_id"),
        "ops_governance_legal_hold",
        ["released_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_legal_hold__tenant_resource_status",
        "ops_governance_legal_hold",
        ["tenant_id", "resource_type", "resource_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_ops_gov_legal_hold__tenant_resource_active",
        "ops_governance_legal_hold",
        ["tenant_id", "resource_type", "resource_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("status = 'active'"),
    )

    op.create_table(
        "ops_governance_lifecycle_action_log",
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
        sa.Column("resource_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("outcome", postgresql.CITEXT(length=32), nullable=False),
        sa.Column(
            "dry_run",
            sa.Boolean(),
            server_default=_sql_text("false"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("correlation_id", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_lifecycle_action_log_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(resource_type)) > 0",
            name="ck_ops_gov_lifecycle_log__resource_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(action_type)) > 0",
            name="ck_ops_gov_lifecycle_log__action_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(outcome)) > 0",
            name="ck_ops_gov_lifecycle_log__outcome_nonempty",
        ),
        sa.CheckConstraint(
            "correlation_id IS NULL OR length(btrim(correlation_id)) > 0",
            name="ck_ops_gov_lifecycle_log__correlation_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_ops_governance_lifecycle_action_log",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_tenant_id"),
        "ops_governance_lifecycle_action_log",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_resource_type"),
        "ops_governance_lifecycle_action_log",
        ["resource_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_resource_id"),
        "ops_governance_lifecycle_action_log",
        ["resource_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_action_type"),
        "ops_governance_lifecycle_action_log",
        ["action_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_outcome"),
        "ops_governance_lifecycle_action_log",
        ["outcome"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_dry_run"),
        "ops_governance_lifecycle_action_log",
        ["dry_run"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_actor_user_id"),
        "ops_governance_lifecycle_action_log",
        ["actor_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_correlation_id"),
        "ops_governance_lifecycle_action_log",
        ["correlation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_lifecycle_log__tenant_resource_created",
        "ops_governance_lifecycle_action_log",
        ["tenant_id", "resource_type", "resource_id", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.add_column(
        "ops_governance_data_handling_record",
        sa.Column("evidence_blob_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_governance_data_handling_record_evidence_blob_id"),
        "ops_governance_data_handling_record",
        ["evidence_blob_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fkx_ops_gov_data_handling_record__tenant_evidence_blob",
        "ops_governance_data_handling_record",
        "audit_evidence_blob",
        ["tenant_id", "evidence_blob_id"],
        ["tenant_id", "id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )

    _execute("""
        CREATE OR REPLACE FUNCTION
            mugen.tg_guard_ops_gov_lifecycle_action_log_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'ops_governance_lifecycle_action_log is append-only'
                USING ERRCODE = 'P0001';
        END;
        $$;
        """)
    _execute("""
        CREATE TRIGGER tr_guard_ops_gov_lifecycle_action_log_update
        BEFORE UPDATE ON mugen.ops_governance_lifecycle_action_log
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_ops_gov_lifecycle_action_log_mutation();
        """)
    _execute("""
        CREATE TRIGGER tr_guard_ops_gov_lifecycle_action_log_delete
        BEFORE DELETE ON mugen.ops_governance_lifecycle_action_log
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_ops_gov_lifecycle_action_log_mutation();
        """)

    _execute("""
        CREATE OR REPLACE FUNCTION mugen.tg_guard_audit_evidence_blob_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.immutability = 'immutable' THEN
                IF
                    NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
                    NEW.trace_id IS DISTINCT FROM OLD.trace_id OR
                    NEW.source_plugin IS DISTINCT FROM OLD.source_plugin OR
                    NEW.subject_namespace IS DISTINCT FROM OLD.subject_namespace OR
                    NEW.subject_id IS DISTINCT FROM OLD.subject_id OR
                    NEW.storage_uri IS DISTINCT FROM OLD.storage_uri OR
                    NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
                    NEW.hash_alg IS DISTINCT FROM OLD.hash_alg OR
                    NEW.content_length IS DISTINCT FROM OLD.content_length OR
                    NEW.immutability IS DISTINCT FROM OLD.immutability OR
                    NEW.meta IS DISTINCT FROM OLD.meta
                THEN
                    RAISE EXCEPTION
                        'audit_evidence_blob immutable payload fields cannot be updated'
                        USING ERRCODE = 'P0001';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """)
    _execute("""
        CREATE TRIGGER tr_guard_audit_evidence_blob_update
        BEFORE UPDATE ON mugen.audit_evidence_blob
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_audit_evidence_blob_update();
        """)


def downgrade() -> None:
    _execute(
        "DROP TRIGGER IF EXISTS tr_guard_audit_evidence_blob_update "
        "ON mugen.audit_evidence_blob;"
    )
    _execute("DROP FUNCTION IF EXISTS mugen.tg_guard_audit_evidence_blob_update();")

    _execute(
        "DROP TRIGGER IF EXISTS tr_guard_ops_gov_lifecycle_action_log_delete "
        "ON mugen.ops_governance_lifecycle_action_log;"
    )
    _execute(
        "DROP TRIGGER IF EXISTS tr_guard_ops_gov_lifecycle_action_log_update "
        "ON mugen.ops_governance_lifecycle_action_log;"
    )
    _execute(
        "DROP FUNCTION IF EXISTS "
        "mugen.tg_guard_ops_gov_lifecycle_action_log_mutation();"
    )

    op.drop_constraint(
        "fkx_ops_gov_data_handling_record__tenant_evidence_blob",
        "ops_governance_data_handling_record",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_data_handling_record_evidence_blob_id"),
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_column(
        "ops_governance_data_handling_record",
        "evidence_blob_id",
        schema=_SCHEMA,
    )

    op.drop_index(
        "ix_ops_gov_lifecycle_log__tenant_resource_created",
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_correlation_id"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_actor_user_id"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_dry_run"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_outcome"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_action_type"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_resource_id"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_resource_type"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_lifecycle_action_log_tenant_id"),
        table_name="ops_governance_lifecycle_action_log",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_lifecycle_action_log", schema=_SCHEMA)

    op.drop_index(
        "ux_ops_gov_legal_hold__tenant_resource_active",
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_legal_hold__tenant_resource_status",
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_released_by_user_id"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_released_at"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_placed_by_user_id"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_placed_at"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_status"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_resource_id"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_resource_type"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_retention_class_id"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_legal_hold_tenant_id"),
        table_name="ops_governance_legal_hold",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_legal_hold", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_gov_retention_class__tenant_resource_active",
        table_name="ops_governance_retention_class",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_retention_class_is_active"),
        table_name="ops_governance_retention_class",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_retention_class_resource_type"),
        table_name="ops_governance_retention_class",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_retention_class_code"),
        table_name="ops_governance_retention_class",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_governance_retention_class_tenant_id"),
        table_name="ops_governance_retention_class",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_retention_class", schema=_SCHEMA)

    op.drop_index(
        "ix_audit_evidence_blob__tenant_content_hash",
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_audit_evidence_blob__tenant_trace",
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_purged_by_user_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_purged_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_purge_due_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_tombstoned_by_user_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_tombstoned_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_released_by_user_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_released_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_by_user_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_legal_hold_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_redacted_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_redaction_due_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_retention_until"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_verified_by_user_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_verified_at"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_verification_status"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_content_hash"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_subject_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_subject_namespace"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_source_plugin"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_trace_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_audit_evidence_blob_tenant_id"),
        table_name="audit_evidence_blob",
        schema=_SCHEMA,
    )
    op.drop_table("audit_evidence_blob", schema=_SCHEMA)

    op.drop_index(
        "ux_plugin_capability_grant__tenant_plugin_active",
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_plugin_capability_grant__tenant_plugin",
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_revoked_by_user_id"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_revoked_at"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_expires_at"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_granted_by_user_id"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_granted_at"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_plugin_key"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_plugin_capability_grant_tenant_id"),
        table_name="admin_plugin_capability_grant",
        schema=_SCHEMA,
    )
    op.drop_table("admin_plugin_capability_grant", schema=_SCHEMA)

    op.drop_index(
        "ux_key_ref__tenant_purpose_active",
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_key_ref__tenant_purpose_status",
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_destroyed_by_user_id"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_destroyed_at"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_retired_by_user_id"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_retired_at"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_status"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_key_id"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_purpose"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_admin_key_ref_tenant_id"),
        table_name="admin_key_ref",
        schema=_SCHEMA,
    )
    op.drop_table("admin_key_ref", schema=_SCHEMA)

    _execute("DROP TYPE IF EXISTS mugen.admin_key_ref_status;")
