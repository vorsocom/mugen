"""ACP-owned messaging client profiles

Revision ID: 6d5f8a2c1b3e
Revises: 5a8c1e2d9f3b
Create Date: 2026-03-08 18:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from migrations.schema_contract import rewrite_mugen_schema_sql
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6d5f8a2c1b3e"
down_revision: Union[str, Sequence[str], None] = "5a8c1e2d9f3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_DEFAULT_RUNTIME_PROFILE_KEY = "default"
_PROFILED_CHANNELS = (
    "line",
    "matrix",
    "signal",
    "telegram",
    "wechat",
    "whatsapp",
)
_PROFILED_CHANNELS_SQL = ", ".join(f"'{channel}'" for channel in _PROFILED_CHANNELS)
_RUNTIME_STATE_TABLES = (
    "messaging_ingress_dead_letter",
    "messaging_ingress_event",
    "messaging_ingress_dedup",
    "messaging_ingress_checkpoint",
)


def _sql(statement: str) -> str:
    return rewrite_mugen_schema_sql(statement, schema=_SCHEMA)


def _sql_text(statement: str):
    return sa.text(_sql(statement))


def _execute(statement) -> None:
    if isinstance(statement, str):
        op.execute(_sql(statement))
        return
    op.execute(statement)


def _clear_runtime_state() -> None:
    for table_name in _RUNTIME_STATE_TABLES:
        _execute(f"DELETE FROM {_SCHEMA}.{table_name};")


def upgrade() -> None:
    op.create_table(
        "admin_messaging_client_profile",
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
        sa.Column("platform_key", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("display_name", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("secret_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("path_token", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("recipient_user_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("account_number", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("phone_number_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("provider", postgresql.CITEXT(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_msg_client_profile_tenant",
        ),
        sa.CheckConstraint(
            "length(btrim(platform_key)) > 0",
            name="ck_msg_client_profile__platform_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(profile_key)) > 0",
            name="ck_msg_client_profile__profile_key_nonempty",
        ),
        sa.CheckConstraint(
            "display_name IS NULL OR length(btrim(display_name)) > 0",
            name="ck_msg_client_profile__display_name_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "path_token IS NULL OR length(btrim(path_token)) > 0",
            name="ck_msg_client_profile__path_token_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "recipient_user_id IS NULL OR length(btrim(recipient_user_id)) > 0",
            name="ck_msg_client_profile__recipient_user_id_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "account_number IS NULL OR length(btrim(account_number)) > 0",
            name="ck_msg_client_profile__account_number_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "phone_number_id IS NULL OR length(btrim(phone_number_id)) > 0",
            name="ck_msg_client_profile__phone_number_id_nonempty_if_set",
        ),
        sa.CheckConstraint(
            "provider IS NULL OR length(btrim(provider)) > 0",
            name="ck_msg_client_profile__provider_nonempty_if_set",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_messaging_client_profile"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_msg_client_profile__tenant_id_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "platform_key",
            "profile_key",
            name="ux_msg_client_profile__tenant_platform_profile",
        ),
        schema=_SCHEMA,
    )
    for index_name, columns in (
        (op.f("ix_mugen_admin_messaging_client_profile_tenant_id"), ["tenant_id"]),
        (op.f("ix_mugen_admin_messaging_client_profile_platform_key"), ["platform_key"]),
        (op.f("ix_mugen_admin_messaging_client_profile_profile_key"), ["profile_key"]),
        (op.f("ix_mugen_admin_messaging_client_profile_is_active"), ["is_active"]),
        (op.f("ix_mugen_admin_messaging_client_profile_path_token"), ["path_token"]),
        (
            op.f("ix_mugen_admin_messaging_client_profile_recipient_user_id"),
            ["recipient_user_id"],
        ),
        (
            op.f("ix_mugen_admin_messaging_client_profile_account_number"),
            ["account_number"],
        ),
        (
            op.f("ix_mugen_admin_messaging_client_profile_phone_number_id"),
            ["phone_number_id"],
        ),
        (op.f("ix_mugen_admin_messaging_client_profile_provider"), ["provider"]),
    ):
        op.create_index(
            index_name,
            "admin_messaging_client_profile",
            columns,
            unique=False,
            schema=_SCHEMA,
        )
    op.create_index(
        "ix_msg_client_profile__tenant_platform_active",
        "admin_messaging_client_profile",
        ["tenant_id", "platform_key", "is_active"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_msg_client_profile__platform_path_token_active",
        "admin_messaging_client_profile",
        ["platform_key", "path_token"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("is_active = true AND path_token IS NOT NULL"),
    )
    op.create_index(
        "ux_msg_client_profile__platform_recipient_user_active",
        "admin_messaging_client_profile",
        ["platform_key", "recipient_user_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text(
            "is_active = true AND recipient_user_id IS NOT NULL"
        ),
    )
    op.create_index(
        "ux_msg_client_profile__platform_account_number_active",
        "admin_messaging_client_profile",
        ["platform_key", "account_number"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text("is_active = true AND account_number IS NOT NULL"),
    )
    op.create_index(
        "ux_msg_client_profile__platform_phone_number_active",
        "admin_messaging_client_profile",
        ["platform_key", "phone_number_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=_sql_text(
            "is_active = true AND phone_number_id IS NOT NULL"
        ),
    )

    op.add_column(
        "channel_orchestration_channel_profile",
        sa.Column("client_profile_id", sa.UUID(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_foreign_key(
        "fk_chorch_profile__client_profile_id",
        "channel_orchestration_channel_profile",
        "admin_messaging_client_profile",
        ["client_profile_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_mugen_channel_orchestration_channel_profile_client_profile_id"),
        "channel_orchestration_channel_profile",
        ["client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_profile__tenant_channel_client_profile",
        "channel_orchestration_channel_profile",
        ["tenant_id", "channel_key", "client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_profile__tenant_channel_runtime_profile",
        table_name="channel_orchestration_channel_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_profile__runtime_profile_key",
        table_name="channel_orchestration_channel_profile",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_chorch_profile__runtime_profile_nonempty_if_set",
        "channel_orchestration_channel_profile",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(
        "channel_orchestration_channel_profile",
        "runtime_profile_key",
        schema=_SCHEMA,
    )

    _clear_runtime_state()

    op.add_column(
        "messaging_ingress_event",
        sa.Column("client_profile_id", sa.UUID(), nullable=True),
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_event_platform_profile_status",
        table_name="messaging_ingress_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_event_runtime_profile_key",
        table_name="messaging_ingress_event",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_msg_ingress_event_runtime_profile_nonempty",
        "messaging_ingress_event",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column("messaging_ingress_event", "runtime_profile_key", schema=_SCHEMA)
    op.alter_column(
        "messaging_ingress_event",
        "client_profile_id",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_messaging_ingress_event_client_profile_id"),
        "messaging_ingress_event",
        ["client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_event_platform_profile_status",
        "messaging_ingress_event",
        ["platform", "client_profile_id", "status"],
        unique=False,
        schema=_SCHEMA,
    )

    op.add_column(
        "messaging_ingress_dedup",
        sa.Column("client_profile_id", sa.UUID(), nullable=True),
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_dedup_expiry",
        table_name="messaging_ingress_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_dedup_runtime_profile_key",
        table_name="messaging_ingress_dedup",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_msg_ingress_dedup_platform_profile_key",
        "messaging_ingress_dedup",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "ck_msg_ingress_dedup_runtime_profile_nonempty",
        "messaging_ingress_dedup",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column("messaging_ingress_dedup", "runtime_profile_key", schema=_SCHEMA)
    op.alter_column(
        "messaging_ingress_dedup",
        "client_profile_id",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_messaging_ingress_dedup_client_profile_id"),
        "messaging_ingress_dedup",
        ["client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_msg_ingress_dedup_platform_profile_key",
        "messaging_ingress_dedup",
        ["platform", "client_profile_id", "dedupe_key"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_dedup_expiry",
        "messaging_ingress_dedup",
        ["platform", "client_profile_id", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.add_column(
        "messaging_ingress_dead_letter",
        sa.Column("client_profile_id", sa.UUID(), nullable=True),
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_dead_letter_runtime_profile_key",
        table_name="messaging_ingress_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_msg_ingress_dead_letter_runtime_profile_nonempty",
        "messaging_ingress_dead_letter",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(
        "messaging_ingress_dead_letter",
        "runtime_profile_key",
        schema=_SCHEMA,
    )
    op.alter_column(
        "messaging_ingress_dead_letter",
        "client_profile_id",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_messaging_ingress_dead_letter_client_profile_id"),
        "messaging_ingress_dead_letter",
        ["client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.add_column(
        "messaging_ingress_checkpoint",
        sa.Column("client_profile_id", sa.UUID(), nullable=True),
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_checkpoint_platform_profile",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_checkpoint_runtime_profile_key",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_msg_ingress_checkpoint_platform_profile_key",
        "messaging_ingress_checkpoint",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "ck_msg_ingress_checkpoint_runtime_profile_nonempty",
        "messaging_ingress_checkpoint",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(
        "messaging_ingress_checkpoint",
        "runtime_profile_key",
        schema=_SCHEMA,
    )
    op.alter_column(
        "messaging_ingress_checkpoint",
        "client_profile_id",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_messaging_ingress_checkpoint_client_profile_id"),
        "messaging_ingress_checkpoint",
        ["client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_msg_ingress_checkpoint_platform_profile_key",
        "messaging_ingress_checkpoint",
        ["platform", "client_profile_id", "checkpoint_key"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_checkpoint_platform_profile",
        "messaging_ingress_checkpoint",
        ["platform", "client_profile_id"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.add_column(
        "messaging_ingress_checkpoint",
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    _execute(
        f"""
        UPDATE {_SCHEMA}.messaging_ingress_checkpoint
           SET runtime_profile_key = client_profile_id::text
         WHERE runtime_profile_key IS NULL;
        """
    )
    op.alter_column(
        "messaging_ingress_checkpoint",
        "runtime_profile_key",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_msg_ingress_checkpoint_runtime_profile_nonempty",
        "messaging_ingress_checkpoint",
        "length(btrim(runtime_profile_key)) > 0",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_checkpoint_platform_profile",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_msg_ingress_checkpoint_platform_profile_key",
        "messaging_ingress_checkpoint",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_index(
        op.f("ix_mugen_messaging_ingress_checkpoint_client_profile_id"),
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_checkpoint_runtime_profile_key",
        "messaging_ingress_checkpoint",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_msg_ingress_checkpoint_platform_profile_key",
        "messaging_ingress_checkpoint",
        ["platform", "runtime_profile_key", "checkpoint_key"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_checkpoint_platform_profile",
        "messaging_ingress_checkpoint",
        ["platform", "runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.drop_column(
        "messaging_ingress_checkpoint",
        "client_profile_id",
        schema=_SCHEMA,
    )

    op.add_column(
        "messaging_ingress_dead_letter",
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    _execute(
        f"""
        UPDATE {_SCHEMA}.messaging_ingress_dead_letter
           SET runtime_profile_key = client_profile_id::text
         WHERE runtime_profile_key IS NULL;
        """
    )
    op.alter_column(
        "messaging_ingress_dead_letter",
        "runtime_profile_key",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_msg_ingress_dead_letter_runtime_profile_nonempty",
        "messaging_ingress_dead_letter",
        "length(btrim(runtime_profile_key)) > 0",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_messaging_ingress_dead_letter_client_profile_id"),
        table_name="messaging_ingress_dead_letter",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_runtime_profile_key",
        "messaging_ingress_dead_letter",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.drop_column(
        "messaging_ingress_dead_letter",
        "client_profile_id",
        schema=_SCHEMA,
    )

    op.add_column(
        "messaging_ingress_dedup",
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    _execute(
        f"""
        UPDATE {_SCHEMA}.messaging_ingress_dedup
           SET runtime_profile_key = client_profile_id::text
         WHERE runtime_profile_key IS NULL;
        """
    )
    op.alter_column(
        "messaging_ingress_dedup",
        "runtime_profile_key",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_msg_ingress_dedup_runtime_profile_nonempty",
        "messaging_ingress_dedup",
        "length(btrim(runtime_profile_key)) > 0",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_dedup_expiry",
        table_name="messaging_ingress_dedup",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ux_msg_ingress_dedup_platform_profile_key",
        "messaging_ingress_dedup",
        schema=_SCHEMA,
        type_="unique",
    )
    op.drop_index(
        op.f("ix_mugen_messaging_ingress_dedup_client_profile_id"),
        table_name="messaging_ingress_dedup",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_runtime_profile_key",
        "messaging_ingress_dedup",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_unique_constraint(
        "ux_msg_ingress_dedup_platform_profile_key",
        "messaging_ingress_dedup",
        ["platform", "runtime_profile_key", "dedupe_key"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_dedup_expiry",
        "messaging_ingress_dedup",
        ["platform", "runtime_profile_key", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.drop_column("messaging_ingress_dedup", "client_profile_id", schema=_SCHEMA)

    op.add_column(
        "messaging_ingress_event",
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    _execute(
        f"""
        UPDATE {_SCHEMA}.messaging_ingress_event
           SET runtime_profile_key = client_profile_id::text
         WHERE runtime_profile_key IS NULL;
        """
    )
    op.alter_column(
        "messaging_ingress_event",
        "runtime_profile_key",
        nullable=False,
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_msg_ingress_event_runtime_profile_nonempty",
        "messaging_ingress_event",
        "length(btrim(runtime_profile_key)) > 0",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_event_platform_profile_status",
        table_name="messaging_ingress_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_messaging_ingress_event_client_profile_id"),
        table_name="messaging_ingress_event",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_runtime_profile_key",
        "messaging_ingress_event",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_event_platform_profile_status",
        "messaging_ingress_event",
        ["platform", "runtime_profile_key", "status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.drop_column("messaging_ingress_event", "client_profile_id", schema=_SCHEMA)

    op.add_column(
        "channel_orchestration_channel_profile",
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    _execute(
        f"""
        UPDATE {_SCHEMA}.channel_orchestration_channel_profile profile
           SET runtime_profile_key = COALESCE(
               (
                   SELECT client_profile.profile_key::text
                     FROM {_SCHEMA}.admin_messaging_client_profile client_profile
                    WHERE client_profile.id = profile.client_profile_id
               ),
               profile.client_profile_id::text
           )
         WHERE profile.client_profile_id IS NOT NULL;
        """
    )
    _execute(
        f"""
        UPDATE {_SCHEMA}.channel_orchestration_channel_profile
           SET runtime_profile_key = '{_DEFAULT_RUNTIME_PROFILE_KEY}'
         WHERE runtime_profile_key IS NULL
           AND lower(channel_key) IN ({_PROFILED_CHANNELS_SQL});
        """
    )
    op.create_check_constraint(
        "ck_chorch_profile__runtime_profile_nonempty_if_set",
        "channel_orchestration_channel_profile",
        "runtime_profile_key IS NULL OR length(btrim(runtime_profile_key)) > 0",
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_profile__runtime_profile_key",
        "channel_orchestration_channel_profile",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_profile__tenant_channel_runtime_profile",
        "channel_orchestration_channel_profile",
        ["tenant_id", "channel_key", "runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_profile__tenant_channel_client_profile",
        table_name="channel_orchestration_channel_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        op.f("ix_mugen_channel_orchestration_channel_profile_client_profile_id"),
        table_name="channel_orchestration_channel_profile",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "fk_chorch_profile__client_profile_id",
        "channel_orchestration_channel_profile",
        schema=_SCHEMA,
        type_="foreignkey",
    )
    op.drop_column(
        "channel_orchestration_channel_profile",
        "client_profile_id",
        schema=_SCHEMA,
    )

    op.drop_index(
        "ux_msg_client_profile__platform_phone_number_active",
        table_name="admin_messaging_client_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_msg_client_profile__platform_account_number_active",
        table_name="admin_messaging_client_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_msg_client_profile__platform_recipient_user_active",
        table_name="admin_messaging_client_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ux_msg_client_profile__platform_path_token_active",
        table_name="admin_messaging_client_profile",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_client_profile__tenant_platform_active",
        table_name="admin_messaging_client_profile",
        schema=_SCHEMA,
    )
    for index_name in (
        op.f("ix_mugen_admin_messaging_client_profile_provider"),
        op.f("ix_mugen_admin_messaging_client_profile_phone_number_id"),
        op.f("ix_mugen_admin_messaging_client_profile_account_number"),
        op.f("ix_mugen_admin_messaging_client_profile_recipient_user_id"),
        op.f("ix_mugen_admin_messaging_client_profile_path_token"),
        op.f("ix_mugen_admin_messaging_client_profile_is_active"),
        op.f("ix_mugen_admin_messaging_client_profile_profile_key"),
        op.f("ix_mugen_admin_messaging_client_profile_platform_key"),
        op.f("ix_mugen_admin_messaging_client_profile_tenant_id"),
    ):
        op.drop_index(
            index_name,
            table_name="admin_messaging_client_profile",
            schema=_SCHEMA,
        )
    op.drop_table("admin_messaging_client_profile", schema=_SCHEMA)
