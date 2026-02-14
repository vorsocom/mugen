"""ops_governance initial schema

Revision ID: d1f4a7b8c9e0
Revises: c8d9e0f1a2b3
Create Date: 2026-02-13 19:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "d1f4a7b8c9e0"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS mugen;")

    ops_governance_consent_status = postgresql.ENUM(
        "granted",
        "withdrawn",
        name="ops_governance_consent_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_governance_delegation_status = postgresql.ENUM(
        "active",
        "revoked",
        "expired",
        name="ops_governance_delegation_status",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_governance_policy_decision = postgresql.ENUM(
        "allow",
        "deny",
        "warn",
        "review",
        name="ops_governance_policy_decision",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_governance_policy_outcome = postgresql.ENUM(
        "applied",
        "blocked",
        "deferred",
        name="ops_governance_policy_outcome",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_governance_retention_action_mode = postgresql.ENUM(
        "mark",
        "redact",
        "erase",
        "archive",
        name="ops_governance_retention_action_mode",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_governance_data_request_type = postgresql.ENUM(
        "retention",
        "redaction",
        "erasure",
        "access",
        name="ops_governance_data_request_type",
        schema=_SCHEMA,
        create_type=False,
    )
    ops_governance_data_request_status = postgresql.ENUM(
        "pending",
        "in_progress",
        "completed",
        "failed",
        "cancelled",
        name="ops_governance_data_request_status",
        schema=_SCHEMA,
        create_type=False,
    )

    bind = op.get_bind()
    ops_governance_consent_status.create(bind, checkfirst=True)
    ops_governance_delegation_status.create(bind, checkfirst=True)
    ops_governance_policy_decision.create(bind, checkfirst=True)
    ops_governance_policy_outcome.create(bind, checkfirst=True)
    ops_governance_retention_action_mode.create(bind, checkfirst=True)
    ops_governance_data_request_type.create(bind, checkfirst=True)
    ops_governance_data_request_status.create(bind, checkfirst=True)

    op.create_table(
        "ops_governance_consent_record",
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
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "controller_namespace",
            postgresql.CITEXT(length=128),
            nullable=False,
        ),
        sa.Column("purpose", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("scope", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("legal_basis", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "status",
            ops_governance_consent_status,
            server_default=sa.text("'granted'"),
            nullable=False,
        ),
        sa.Column(
            "effective_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_consent_id", sa.Uuid(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("withdrawal_reason", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_consent_record__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(controller_namespace)) > 0",
            name="ck_ops_gov_consent_record__controller_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(purpose)) > 0",
            name="ck_ops_gov_consent_record__purpose_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(scope)) > 0",
            name="ck_ops_gov_consent_record__scope_nonempty",
        ),
        sa.CheckConstraint(
            "legal_basis IS NULL OR length(btrim(legal_basis)) > 0",
            name="ck_ops_gov_consent_record__legal_basis_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "withdrawal_reason IS NULL OR"
                " length(btrim(withdrawal_reason)) > 0"
            ),
            name="ck_ops_gov_consent_record__withdrawal_reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_gov_consent_record"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_consent_record__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__tenant_id",
        "ops_governance_consent_record",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__subject_user_id",
        "ops_governance_consent_record",
        ["subject_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__status",
        "ops_governance_consent_record",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__effective_at",
        "ops_governance_consent_record",
        ["effective_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__source_consent_id",
        "ops_governance_consent_record",
        ["source_consent_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__withdrawn_at",
        "ops_governance_consent_record",
        ["withdrawn_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_consent_record__tenant_subject_effective",
        "ops_governance_consent_record",
        ["tenant_id", "subject_user_id", "effective_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_delegation_grant",
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
        sa.Column("principal_user_id", sa.Uuid(), nullable=False),
        sa.Column("delegate_user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=1024), nullable=True),
        sa.Column(
            "status",
            ops_governance_delegation_status,
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_grant_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=1024), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_delegation_grant__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "principal_user_id <> delegate_user_id",
            name="ck_ops_gov_delegation_grant__principal_delegate_distinct",
        ),
        sa.CheckConstraint(
            "length(btrim(scope)) > 0",
            name="ck_ops_gov_delegation_grant__scope_nonempty",
        ),
        sa.CheckConstraint(
            "purpose IS NULL OR length(btrim(purpose)) > 0",
            name="ck_ops_gov_delegation_grant__purpose_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "revocation_reason IS NULL OR"
                " length(btrim(revocation_reason)) > 0"
            ),
            name="ck_ops_gov_delegation_grant__revocation_reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_gov_delegation_grant"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_delegation_grant__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__tenant_id",
        "ops_governance_delegation_grant",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__principal_user_id",
        "ops_governance_delegation_grant",
        ["principal_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__delegate_user_id",
        "ops_governance_delegation_grant",
        ["delegate_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__status",
        "ops_governance_delegation_grant",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__effective_from",
        "ops_governance_delegation_grant",
        ["effective_from"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__source_grant_id",
        "ops_governance_delegation_grant",
        ["source_grant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__revoked_at",
        "ops_governance_delegation_grant",
        ["revoked_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_delegation_grant__tenant_principal_delegate_status",
        "ops_governance_delegation_grant",
        ["tenant_id", "principal_user_id", "delegate_user_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_policy_definition",
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
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column("policy_type", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("rule_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "evaluation_mode",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'advisory'"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_evaluated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("last_decision_log_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_policy_definition__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_gov_policy_definition__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_gov_policy_definition__name_nonempty",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_gov_policy_definition__description_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "policy_type IS NULL OR length(btrim(policy_type)) > 0",
            name="ck_ops_gov_policy_definition__policy_type_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "rule_ref IS NULL OR length(btrim(rule_ref)) > 0",
            name="ck_ops_gov_policy_definition__rule_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "length(btrim(evaluation_mode)) > 0",
            name="ck_ops_gov_policy_definition__evaluation_mode_nonempty",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_ops_gov_policy_definition__version_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_gov_policy_definition"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_policy_definition__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_gov_policy_definition__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_definition__tenant_id",
        "ops_governance_policy_definition",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_definition__code",
        "ops_governance_policy_definition",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_definition__policy_type",
        "ops_governance_policy_definition",
        ["policy_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_definition__is_active",
        "ops_governance_policy_definition",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_definition__last_evaluated_at",
        "ops_governance_policy_definition",
        ["last_evaluated_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_definition__tenant_type_active",
        "ops_governance_policy_definition",
        ["tenant_id", "policy_type", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_policy_decision_log",
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
        sa.Column("policy_definition_id", sa.Uuid(), nullable=False),
        sa.Column("subject_namespace", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("subject_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("decision", ops_governance_policy_decision, nullable=False),
        sa.Column(
            "outcome",
            ops_governance_policy_outcome,
            server_default=sa.text("'applied'"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("evaluator_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "request_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_policy_decision_log__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "policy_definition_id"],
            [
                "mugen.ops_governance_policy_definition.tenant_id",
                "mugen.ops_governance_policy_definition.id",
            ],
            ondelete="CASCADE",
            name="fkx_ops_gov_policy_decision_log__tenant_policy_definition",
        ),
        sa.CheckConstraint(
            "length(btrim(subject_namespace)) > 0",
            name="ck_ops_gov_policy_decision_log__subject_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "subject_ref IS NULL OR length(btrim(subject_ref)) > 0",
            name="ck_ops_gov_policy_decision_log__subject_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_ops_gov_policy_decision_log__reason_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_gov_policy_decision_log"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_policy_decision_log__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__tenant_id",
        "ops_governance_policy_decision_log",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__policy_definition_id",
        "ops_governance_policy_decision_log",
        ["policy_definition_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__subject_namespace",
        "ops_governance_policy_decision_log",
        ["subject_namespace"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__decision",
        "ops_governance_policy_decision_log",
        ["decision"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__outcome",
        "ops_governance_policy_decision_log",
        ["outcome"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__evaluated_at",
        "ops_governance_policy_decision_log",
        ["evaluated_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__retention_until",
        "ops_governance_policy_decision_log",
        ["retention_until"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_policy_decision_log__tenant_policy_eval",
        "ops_governance_policy_decision_log",
        ["tenant_id", "policy_definition_id", "evaluated_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_retention_policy",
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
        sa.Column("code", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("target_namespace", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("target_entity", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column(
            "retention_days",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("redaction_after_days", sa.BigInteger(), nullable=True),
        sa.Column(
            "legal_hold_allowed",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "action_mode",
            ops_governance_retention_action_mode,
            server_default=sa.text("'mark'"),
            nullable=False,
        ),
        sa.Column("downstream_job_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("last_action_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_action_type", postgresql.CITEXT(length=64), nullable=True),
        sa.Column("last_action_status", postgresql.CITEXT(length=32), nullable=True),
        sa.Column("last_action_note", sa.String(length=1024), nullable=True),
        sa.Column("last_action_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_retention_policy__tenant_id__admin_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(code)) > 0",
            name="ck_ops_gov_retention_policy__code_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_ops_gov_retention_policy__name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(target_namespace)) > 0",
            name="ck_ops_gov_retention_policy__target_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "target_entity IS NULL OR length(btrim(target_entity)) > 0",
            name="ck_ops_gov_retention_policy__target_entity_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(btrim(description)) > 0",
            name="ck_ops_gov_retention_policy__description_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "retention_days >= 0",
            name="ck_ops_gov_retention_policy__retention_days_nonnegative",
        ),
        sa.CheckConstraint(
            (
                "redaction_after_days IS NULL OR"
                " redaction_after_days >= 0"
            ),
            name="ck_ops_gov_retention_policy__redaction_days_nonnegative",
        ),
        sa.CheckConstraint(
            (
                "downstream_job_ref IS NULL OR"
                " length(btrim(downstream_job_ref)) > 0"
            ),
            name="ck_ops_gov_retention_policy__downstream_job_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "last_action_type IS NULL OR"
                " length(btrim(last_action_type)) > 0"
            ),
            name="ck_ops_gov_retention_policy__last_action_type_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "last_action_status IS NULL OR"
                " length(btrim(last_action_status)) > 0"
            ),
            name="ck_ops_gov_retention_policy__last_action_status_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "last_action_note IS NULL OR"
                " length(btrim(last_action_note)) > 0"
            ),
            name="ck_ops_gov_retention_policy__last_action_note_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_gov_retention_policy"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_retention_policy__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "code",
            name="ux_ops_gov_retention_policy__tenant_code",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__tenant_id",
        "ops_governance_retention_policy",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__code",
        "ops_governance_retention_policy",
        ["code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__target_namespace",
        "ops_governance_retention_policy",
        ["target_namespace"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__target_entity",
        "ops_governance_retention_policy",
        ["target_entity"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__is_active",
        "ops_governance_retention_policy",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__last_action_applied_at",
        "ops_governance_retention_policy",
        ["last_action_applied_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_retention_policy__tenant_target_active",
        "ops_governance_retention_policy",
        ["tenant_id", "target_namespace", "target_entity", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_governance_data_handling_record",
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
        sa.Column("retention_policy_id", sa.Uuid(), nullable=True),
        sa.Column("subject_namespace", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("subject_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "request_type",
            ops_governance_data_request_type,
            server_default=sa.text("'retention'"),
            nullable=False,
        ),
        sa.Column(
            "request_status",
            ops_governance_data_request_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(length=2048), nullable=True),
        sa.Column("handled_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_ref", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_gov_data_handling_record__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "retention_policy_id"],
            [
                "mugen.ops_governance_retention_policy.tenant_id",
                "mugen.ops_governance_retention_policy.id",
            ],
            ondelete="SET NULL",
            name="fkx_ops_gov_data_handling_record__tenant_retention_policy",
        ),
        sa.CheckConstraint(
            "length(btrim(subject_namespace)) > 0",
            name="ck_ops_gov_data_handling_record__subject_namespace_nonempty",
        ),
        sa.CheckConstraint(
            "subject_ref IS NULL OR length(btrim(subject_ref)) > 0",
            name="ck_ops_gov_data_handling_record__subject_ref_nonempty_if_set",
        ),
        sa.CheckConstraint(
            (
                "resolution_note IS NULL OR"
                " length(btrim(resolution_note)) > 0"
            ),
            name="ck_ops_gov_data_handling_record__resolution_note_nonempty",
        ),
        sa.CheckConstraint(
            "evidence_ref IS NULL OR length(btrim(evidence_ref)) > 0",
            name="ck_ops_gov_data_handling_record__evidence_ref_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_gov_data_handling_record"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_gov_data_handling_record__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__tenant_id",
        "ops_governance_data_handling_record",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__retention_policy_id",
        "ops_governance_data_handling_record",
        ["retention_policy_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__subject_namespace",
        "ops_governance_data_handling_record",
        ["subject_namespace"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__request_type",
        "ops_governance_data_handling_record",
        ["request_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__request_status",
        "ops_governance_data_handling_record",
        ["request_status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__requested_at",
        "ops_governance_data_handling_record",
        ["requested_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__due_at",
        "ops_governance_data_handling_record",
        ["due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__completed_at",
        "ops_governance_data_handling_record",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_gov_data_handling_record__tenant_status_requested",
        "ops_governance_data_handling_record",
        ["tenant_id", "request_status", "requested_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ops_gov_data_handling_record__tenant_status_requested",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__completed_at",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__due_at",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__requested_at",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__request_status",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__request_type",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__subject_namespace",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__retention_policy_id",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_data_handling_record__tenant_id",
        table_name="ops_governance_data_handling_record",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_data_handling_record", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_gov_retention_policy__tenant_target_active",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_retention_policy__last_action_applied_at",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_retention_policy__is_active",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_retention_policy__target_entity",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_retention_policy__target_namespace",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_retention_policy__code",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_retention_policy__tenant_id",
        table_name="ops_governance_retention_policy",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_retention_policy", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_gov_policy_decision_log__tenant_policy_eval",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__retention_until",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__evaluated_at",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__outcome",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__decision",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__subject_namespace",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__policy_definition_id",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_decision_log__tenant_id",
        table_name="ops_governance_policy_decision_log",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_policy_decision_log", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_gov_policy_definition__tenant_type_active",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_definition__last_evaluated_at",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_definition__is_active",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_definition__policy_type",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_definition__code",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_policy_definition__tenant_id",
        table_name="ops_governance_policy_definition",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_policy_definition", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_gov_delegation_grant__tenant_principal_delegate_status",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__revoked_at",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__source_grant_id",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__effective_from",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__status",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__delegate_user_id",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__principal_user_id",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_delegation_grant__tenant_id",
        table_name="ops_governance_delegation_grant",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_delegation_grant", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_gov_consent_record__tenant_subject_effective",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_consent_record__withdrawn_at",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_consent_record__source_consent_id",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_consent_record__effective_at",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_consent_record__status",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_consent_record__subject_user_id",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_gov_consent_record__tenant_id",
        table_name="ops_governance_consent_record",
        schema=_SCHEMA,
    )
    op.drop_table("ops_governance_consent_record", schema=_SCHEMA)

    bind = op.get_bind()
    postgresql.ENUM(
        name="ops_governance_data_request_status",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="ops_governance_data_request_type",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="ops_governance_retention_action_mode",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="ops_governance_policy_outcome",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="ops_governance_policy_decision",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="ops_governance_delegation_status",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        name="ops_governance_consent_status",
        schema=_SCHEMA,
    ).drop(bind, checkfirst=True)
