"""phase6 ops_connector schema for connector runtime + immutable call logs

Revision ID: d9f2a4b6c8e0
Revises: b7c9d1e3f5a7
Create Date: 2026-02-26 18:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "d9f2a4b6c8e0"
down_revision: Union[str, Sequence[str], None] = "b7c9d1e3f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    instance_status = postgresql.ENUM(
        "active",
        "disabled",
        "error",
        name="ops_connector_instance_status",
        schema=_SCHEMA,
        create_type=False,
    )
    call_log_status = postgresql.ENUM(
        "ok",
        "retrying",
        "failed",
        name="ops_connector_call_log_status",
        schema=_SCHEMA,
        create_type=False,
    )
    bind = op.get_bind()
    instance_status.create(bind, checkfirst=True)
    call_log_status.create(bind, checkfirst=True)

    op.create_table(
        "ops_connector_type",
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
        sa.Column("key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "adapter_kind",
            postgresql.CITEXT(length=64),
            nullable=False,
            server_default=sa.text("'http_json'"),
        ),
        sa.Column(
            "capabilities_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.CheckConstraint(
            "length(btrim(key)) > 0",
            name="ck_ops_connector_type__key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_ops_connector_type__display_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(adapter_kind)) > 0",
            name="ck_ops_connector_type__adapter_kind_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(capabilities_json) = 'object'",
            name="ck_ops_connector_type__capabilities_json_object",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_connector_type"),
        sa.UniqueConstraint("key", name="ux_ops_connector_type__key"),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_type_key"),
        "ops_connector_type",
        ["key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_type_adapter_kind"),
        "ops_connector_type",
        ["adapter_kind"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_type_is_active"),
        "ops_connector_type",
        ["is_active"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_connector_instance",
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
        sa.Column("connector_type_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("secret_ref", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "status",
            instance_status,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "escalation_policy_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        sa.Column(
            "retry_policy_json",
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
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_connector_instance__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["connector_type_id"],
            ["mugen.ops_connector_type.id"],
            ondelete="RESTRICT",
            name="fk_ops_connector_instance__connector_type",
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0",
            name="ck_ops_connector_instance__display_name_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(secret_ref)) > 0",
            name="ck_ops_connector_instance__secret_ref_nonempty",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(config_json) = 'object'",
            name="ck_ops_connector_instance__config_json_object",
        ),
        sa.CheckConstraint(
            (
                "retry_policy_json IS NULL OR "
                "jsonb_typeof(retry_policy_json) = 'object'"
            ),
            name="ck_ops_connector_instance__retry_policy_json_object_if_set",
        ),
        sa.CheckConstraint(
            (
                "escalation_policy_key IS NULL OR "
                "length(btrim(escalation_policy_key)) > 0"
            ),
            name="ck_ops_connector_instance__escalation_policy_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_connector_instance"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_connector_instance__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_instance_tenant_id"),
        "ops_connector_instance",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_instance_connector_type_id"),
        "ops_connector_instance",
        ["connector_type_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_instance_status"),
        "ops_connector_instance",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_instance_escalation_policy_key"),
        "ops_connector_instance",
        ["escalation_policy_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_connector_instance__tenant_status",
        "ops_connector_instance",
        ["tenant_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_connector_instance__tenant_type",
        "ops_connector_instance",
        ["tenant_id", "connector_type_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "ops_connector_call_log",
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
        sa.Column("trace_id", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("connector_instance_id", sa.Uuid(), nullable=False),
        sa.Column("capability_name", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("client_action_key", postgresql.CITEXT(length=128), nullable=True),
        sa.Column(
            "request_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_hash", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "response_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("response_hash", postgresql.CITEXT(length=64), nullable=True),
        sa.Column(
            "status",
            call_log_status,
            nullable=False,
            server_default=sa.text("'failed'"),
        ),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column(
            "attempt_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "error_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "escalation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("invoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "invoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["mugen.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_ops_connector_call_log__tenant_id__admin_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["invoked_by_user_id"],
            ["mugen.admin_user.id"],
            ondelete="SET NULL",
            name="fk_ops_connector_call_log__invoked_by_user_id__admin_user",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "connector_instance_id"],
            [
                "mugen.ops_connector_instance.tenant_id",
                "mugen.ops_connector_instance.id",
            ],
            ondelete="RESTRICT",
            name="fkx_ops_connector_call_log__tenant_instance",
        ),
        sa.CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_ops_connector_call_log__trace_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(capability_name)) > 0",
            name="ck_ops_connector_call_log__capability_name_nonempty",
        ),
        sa.CheckConstraint(
            ("client_action_key IS NULL OR " "length(btrim(client_action_key)) > 0"),
            name="ck_ops_connector_call_log__client_action_key_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "length(btrim(request_hash)) > 0",
            name="ck_ops_connector_call_log__request_hash_nonempty",
        ),
        sa.CheckConstraint(
            ("response_hash IS NULL OR " "length(btrim(response_hash)) > 0"),
            name="ck_ops_connector_call_log__response_hash_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "attempt_count >= 1",
            name="ck_ops_connector_call_log__attempt_count_positive",
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_ops_connector_call_log__duration_ms_nonnegative_if_set",
        ),
        sa.CheckConstraint(
            (
                "http_status_code IS NULL OR "
                "(http_status_code >= 100 AND http_status_code <= 599)"
            ),
            name="ck_ops_connector_call_log__http_status_code_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ops_connector_call_log"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_ops_connector_call_log__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_tenant_id"),
        "ops_connector_call_log",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_trace_id"),
        "ops_connector_call_log",
        ["trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_connector_instance_id"),
        "ops_connector_call_log",
        ["connector_instance_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_client_action_key"),
        "ops_connector_call_log",
        ["client_action_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_status"),
        "ops_connector_call_log",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_invoked_by_user_id"),
        "ops_connector_call_log",
        ["invoked_by_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_ops_connector_call_log_invoked_at"),
        "ops_connector_call_log",
        ["invoked_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_connector_call_log__tenant_trace",
        "ops_connector_call_log",
        ["tenant_id", "trace_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_connector_call_log__tenant_instance_created",
        "ops_connector_call_log",
        ["tenant_id", "connector_instance_id", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_ops_connector_call_log__tenant_status_created",
        "ops_connector_call_log",
        ["tenant_id", "status", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION mugen.tg_guard_ops_connector_call_log_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'ops_connector_call_log is immutable; UPDATE/DELETE are not allowed'
                USING ERRCODE = 'P0001';
        END;
        $$;
        """)
    op.execute("""
        CREATE TRIGGER tr_guard_ops_connector_call_log_update
        BEFORE UPDATE ON mugen.ops_connector_call_log
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_ops_connector_call_log_mutation();
        """)
    op.execute("""
        CREATE TRIGGER tr_guard_ops_connector_call_log_delete
        BEFORE DELETE ON mugen.ops_connector_call_log
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_ops_connector_call_log_mutation();
        """)

    op.execute("""
        INSERT INTO mugen.ops_connector_type (
            id,
            key,
            display_name,
            adapter_kind,
            capabilities_json,
            is_active
        )
        SELECT
            '6f886d5e-6a4d-4d7c-8d27-2f4878fbc4d0'::uuid,
            'http_json_default',
            'HTTP JSON Default',
            'http_json',
            jsonb_build_object(
                'get_jwks',
                jsonb_build_object(
                    'Method',
                    'GET',
                    'PathTemplate',
                    '/api/core/acp/v1/auth/.well-known/jwks.json',
                    'InputPlacement',
                    'query',
                    'Headers',
                    jsonb_build_object()
                )
            ),
            true
        WHERE NOT EXISTS (
            SELECT 1
            FROM mugen.ops_connector_type
            WHERE key = 'http_json_default'
        );
        """)

    op.execute("""
        INSERT INTO mugen.admin_key_ref (
            tenant_id,
            purpose,
            key_id,
            provider,
            status,
            attributes
        )
        SELECT
            '00000000-0000-0000-0000-000000000000'::uuid,
            'ops_connector_secret',
            'ops_connector_default',
            'local',
            'active',
            jsonb_build_object(
                'seed_source',
                'phase6_ops_connector'
            )
        WHERE NOT EXISTS (
            SELECT 1
            FROM mugen.admin_key_ref
            WHERE tenant_id = '00000000-0000-0000-0000-000000000000'::uuid
              AND purpose = 'ops_connector_secret'
              AND status = 'active'
        )
        ON CONFLICT (tenant_id, purpose, key_id) DO NOTHING;
        """)

    op.execute("""
        INSERT INTO mugen.admin_plugin_capability_grant (
            tenant_id,
            plugin_key,
            capabilities,
            attributes
        )
        SELECT
            '00000000-0000-0000-0000-000000000000'::uuid,
            'com.vorsocomputing.mugen.ops_connector',
            '[
              "connector:invoke",
              "net:outbound",
              "secrets:read"
            ]'::jsonb,
            jsonb_build_object(
                'seed_source',
                'phase6_ops_connector'
            )
        WHERE NOT EXISTS (
            SELECT 1
            FROM mugen.admin_plugin_capability_grant
            WHERE tenant_id = '00000000-0000-0000-0000-000000000000'::uuid
              AND plugin_key = 'com.vorsocomputing.mugen.ops_connector'
              AND revoked_at IS NULL
        );
        """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM mugen.admin_plugin_capability_grant
        WHERE tenant_id = '00000000-0000-0000-0000-000000000000'::uuid
          AND plugin_key = 'com.vorsocomputing.mugen.ops_connector'
          AND attributes ->> 'seed_source' = 'phase6_ops_connector';
        """)

    op.execute("""
        DELETE FROM mugen.admin_key_ref
        WHERE tenant_id = '00000000-0000-0000-0000-000000000000'::uuid
          AND purpose = 'ops_connector_secret'
          AND key_id = 'ops_connector_default'
          AND attributes ->> 'seed_source' = 'phase6_ops_connector';
        """)

    op.execute(
        "DROP TRIGGER IF EXISTS tr_guard_ops_connector_call_log_delete "
        "ON mugen.ops_connector_call_log;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS tr_guard_ops_connector_call_log_update "
        "ON mugen.ops_connector_call_log;"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS mugen.tg_guard_ops_connector_call_log_mutation();"
    )

    op.drop_index(
        "ix_ops_connector_call_log__tenant_status_created",
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_connector_call_log__tenant_instance_created",
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_connector_call_log__tenant_trace",
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_invoked_at"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_invoked_by_user_id"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_status"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_client_action_key"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_connector_instance_id"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_trace_id"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_call_log_tenant_id"),
        table_name="ops_connector_call_log",
        schema=_SCHEMA,
    )
    op.drop_table("ops_connector_call_log", schema=_SCHEMA)

    op.drop_index(
        "ix_ops_connector_instance__tenant_type",
        table_name="ops_connector_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_ops_connector_instance__tenant_status",
        table_name="ops_connector_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_instance_escalation_policy_key"),
        table_name="ops_connector_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_instance_status"),
        table_name="ops_connector_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_instance_connector_type_id"),
        table_name="ops_connector_instance",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_instance_tenant_id"),
        table_name="ops_connector_instance",
        schema=_SCHEMA,
    )
    op.drop_table("ops_connector_instance", schema=_SCHEMA)

    op.drop_index(
        op.f("ix_mugen_ops_connector_type_is_active"),
        table_name="ops_connector_type",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_type_adapter_kind"),
        table_name="ops_connector_type",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_ops_connector_type_key"),
        table_name="ops_connector_type",
        schema=_SCHEMA,
    )
    op.drop_table("ops_connector_type", schema=_SCHEMA)

    op.execute("DROP TYPE IF EXISTS mugen.ops_connector_call_log_status;")
    op.execute("DROP TYPE IF EXISTS mugen.ops_connector_instance_status;")
