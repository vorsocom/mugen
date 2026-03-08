"""shared messaging ingress tables

Revision ID: 5a8c1e2d9f3b
Revises: 4b7d2e1f9a6c
Create Date: 2026-03-08 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5a8c1e2d9f3b"
down_revision: Union[str, Sequence[str], None] = "4b7d2e1f9a6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_DEFAULT_RUNTIME_PROFILE_KEY = "default"
_LEGACY_DEDUP_TABLES = (
    ("line", "line_messagingapi_event_dedup"),
    ("signal", "signal_restapi_event_dedup"),
    ("telegram", "telegram_botapi_event_dedup"),
    ("wechat", "wechat_event_dedup"),
    ("whatsapp", "whatsapp_wacapi_event_dedup"),
)
_LEGACY_DEAD_LETTER_TABLES = (
    ("line", "line_messagingapi_event_dead_letter", "line_ingress_event", "webhook", "path_token"),
    ("signal", "signal_restapi_event_dead_letter", "signal_ingress_event", "receive_loop", "account_number"),
    ("telegram", "telegram_botapi_event_dead_letter", "telegram_ingress_event", "webhook", "path_token"),
    ("wechat", "wechat_event_dead_letter", "wechat_ingress_event", "webhook", "path_token"),
    ("whatsapp", "whatsapp_wacapi_event_dead_letter", "whatsapp_ingress_event", "webhook", "phone_number_id"),
)
_LEGACY_INDEX_PREFIXES = {
    "line": {
        "dedup": "line_mapi_event_dedup",
        "dead_letter": "line_mapi_dead_letter",
    },
    "signal": {
        "dedup": "signal_restapi_event_dedup",
        "dead_letter": "signal_restapi_dead_letter",
    },
    "telegram": {
        "dedup": "tg_botapi_event_dedup",
        "dead_letter": "tg_botapi_dead_letter",
    },
    "wechat": {
        "dedup": "wechat_event_dedup",
        "dead_letter": "wechat_dead_letter",
    },
    "whatsapp": {
        "dedup": "wacapi_event_dedup",
        "dead_letter": "wacapi_dead_letter",
    },
}


def _table_exists(table_name: str) -> bool:
    if context.is_offline_mode():
        return True
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT to_regclass(:qualified_name)"),
        {"qualified_name": f"{_SCHEMA}.{table_name}"},
    )
    return result.scalar() not in [None, ""]


def _backfill_legacy_dedup(platform: str, table_name: str) -> None:
    if _table_exists(table_name) is not True:
        return
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_SCHEMA}.messaging_ingress_dedup (
                id,
                created_at,
                updated_at,
                row_version,
                platform,
                runtime_profile_key,
                event_type,
                dedupe_key,
                event_id,
                last_seen_at,
                expires_at
            )
            SELECT
                id,
                created_at,
                updated_at,
                row_version,
                '{platform}',
                '{_DEFAULT_RUNTIME_PROFILE_KEY}',
                event_type,
                dedupe_key,
                event_id,
                last_seen_at,
                expires_at
            FROM {_SCHEMA}.{table_name}
            ON CONFLICT (platform, runtime_profile_key, dedupe_key) DO NOTHING
            """
        )
    )


def _backfill_legacy_dead_letter(
    platform: str,
    table_name: str,
    ipc_command: str,
    source_mode: str,
    identifier_type: str,
) -> None:
    if _table_exists(table_name) is not True:
        return
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_SCHEMA}.messaging_ingress_dead_letter (
                id,
                created_at,
                updated_at,
                row_version,
                source_event_id,
                version,
                platform,
                runtime_profile_key,
                ipc_command,
                source_mode,
                event_type,
                event_id,
                dedupe_key,
                identifier_type,
                identifier_value,
                room_id,
                sender,
                payload,
                provider_context,
                received_at,
                reason_code,
                error_message,
                status,
                attempts,
                first_failed_at,
                last_failed_at
            )
            SELECT
                id,
                created_at,
                updated_at,
                row_version,
                NULL,
                1,
                '{platform}',
                '{_DEFAULT_RUNTIME_PROFILE_KEY}',
                '{ipc_command}',
                '{source_mode}',
                event_type,
                NULL,
                COALESCE(dedupe_key, event_type || CHR(58) || 'legacy'),
                '{identifier_type}',
                NULL,
                NULL,
                NULL,
                payload,
                '{{}}'::jsonb,
                COALESCE(created_at, first_failed_at, last_failed_at, now()),
                reason_code,
                error_message,
                status,
                attempts,
                first_failed_at,
                last_failed_at
            FROM {_SCHEMA}.{table_name}
            """
        )
    )


def _drop_legacy_table(table_name: str) -> None:
    if _table_exists(table_name) is True:
        op.drop_table(table_name, schema=_SCHEMA)


def _create_legacy_dedup_table(
    *,
    platform: str,
    table_name: str,
) -> None:
    dedup_prefix = _LEGACY_INDEX_PREFIXES[platform]["dedup"]
    op.create_table(
        table_name,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("dedupe_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("event_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    for index_name, columns in (
        (f"ix_{dedup_prefix}_event_type", ["event_type"]),
        (f"ix_{dedup_prefix}_dedupe_key", ["dedupe_key"]),
        (f"ix_{dedup_prefix}_event_id", ["event_id"]),
        (f"ix_{dedup_prefix}_expiry", ["event_type", "expires_at"]),
        (f"ix_{dedup_prefix}_expires_at", ["expires_at"]),
    ):
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=False,
            schema=_SCHEMA,
        )


def _create_legacy_dead_letter_table(
    *,
    platform: str,
    table_name: str,
) -> None:
    dead_letter_prefix = _LEGACY_INDEX_PREFIXES[platform]["dead_letter"]
    op.create_table(
        table_name,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("dedupe_key", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason_code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("error_message", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    for index_name, columns in (
        (f"ix_{dead_letter_prefix}_event_type", ["event_type"]),
        (f"ix_{dead_letter_prefix}_dedupe_key", ["dedupe_key"]),
        (f"ix_{dead_letter_prefix}_reason_code", ["reason_code"]),
        (f"ix_{dead_letter_prefix}_status", ["status"]),
        (f"ix_{dead_letter_prefix}_last_failed_at", ["last_failed_at"]),
        (f"ix_{dead_letter_prefix}_status_failed_at", ["status", "last_failed_at"]),
    ):
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=False,
            schema=_SCHEMA,
        )


def _restore_legacy_dedup(
    *,
    platform: str,
    table_name: str,
) -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_SCHEMA}.{table_name} (
                id,
                created_at,
                updated_at,
                row_version,
                event_type,
                dedupe_key,
                event_id,
                last_seen_at,
                expires_at
            )
            SELECT
                id,
                created_at,
                updated_at,
                row_version,
                event_type,
                dedupe_key,
                event_id,
                last_seen_at,
                expires_at
            FROM {_SCHEMA}.messaging_ingress_dedup
            WHERE platform = '{platform}'
              AND runtime_profile_key = '{_DEFAULT_RUNTIME_PROFILE_KEY}'
            """
        )
    )


def _restore_legacy_dead_letter(
    *,
    platform: str,
    table_name: str,
) -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_SCHEMA}.{table_name} (
                id,
                created_at,
                updated_at,
                row_version,
                event_type,
                dedupe_key,
                payload,
                reason_code,
                error_message,
                status,
                attempts,
                first_failed_at,
                last_failed_at
            )
            SELECT
                id,
                created_at,
                updated_at,
                row_version,
                event_type,
                dedupe_key,
                payload,
                reason_code,
                error_message,
                status,
                attempts,
                first_failed_at,
                last_failed_at
            FROM {_SCHEMA}.messaging_ingress_dead_letter
            WHERE platform = '{platform}'
              AND runtime_profile_key = '{_DEFAULT_RUNTIME_PROFILE_KEY}'
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "messaging_ingress_event",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("platform", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("ipc_command", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("source_mode", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("event_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("dedupe_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("identifier_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("identifier_value", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("room_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("sender", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "provider_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", postgresql.CITEXT(length=128), nullable=True),
        sa.Column("error_message", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_msg_ingress_event_version_positive"),
        sa.CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_msg_ingress_event_platform_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(runtime_profile_key)) > 0",
            name="ck_msg_ingress_event_runtime_profile_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(ipc_command)) > 0",
            name="ck_msg_ingress_event_ipc_command_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_mode)) > 0",
            name="ck_msg_ingress_event_source_mode_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_msg_ingress_event_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_msg_ingress_event_dedupe_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(identifier_type)) > 0",
            name="ck_msg_ingress_event_identifier_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_msg_ingress_event_status_nonempty",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_msg_ingress_event_attempts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_platform",
        "messaging_ingress_event",
        ["platform"],
        unique=False,
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
        "ix_messaging_ingress_event_ipc_command",
        "messaging_ingress_event",
        ["ipc_command"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_source_mode",
        "messaging_ingress_event",
        ["source_mode"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_event_type",
        "messaging_ingress_event",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_event_id",
        "messaging_ingress_event",
        ["event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_dedupe_key",
        "messaging_ingress_event",
        ["dedupe_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_identifier_value",
        "messaging_ingress_event",
        ["identifier_value"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_room_id",
        "messaging_ingress_event",
        ["room_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_sender",
        "messaging_ingress_event",
        ["sender"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_received_at",
        "messaging_ingress_event",
        ["received_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_status",
        "messaging_ingress_event",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_lease_expires_at",
        "messaging_ingress_event",
        ["lease_expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_event_completed_at",
        "messaging_ingress_event",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_event_status_lease",
        "messaging_ingress_event",
        ["status", "lease_expires_at", "received_at"],
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

    op.create_table(
        "messaging_ingress_dedup",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("platform", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("dedupe_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("event_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_msg_ingress_dedup_platform_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(runtime_profile_key)) > 0",
            name="ck_msg_ingress_dedup_runtime_profile_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_msg_ingress_dedup_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_msg_ingress_dedup_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "runtime_profile_key",
            "dedupe_key",
            name="ux_msg_ingress_dedup_platform_profile_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_platform",
        "messaging_ingress_dedup",
        ["platform"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_runtime_profile_key",
        "messaging_ingress_dedup",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_event_type",
        "messaging_ingress_dedup",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_dedupe_key",
        "messaging_ingress_dedup",
        ["dedupe_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_event_id",
        "messaging_ingress_dedup",
        ["event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dedup_expires_at",
        "messaging_ingress_dedup",
        ["expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_dedup_expiry",
        "messaging_ingress_dedup",
        ["platform", "runtime_profile_key", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "messaging_ingress_dead_letter",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("platform", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("ipc_command", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("source_mode", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("event_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("dedupe_key", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("identifier_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("identifier_value", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("room_id", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("sender", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "provider_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason_code", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("error_message", postgresql.CITEXT(length=1024), nullable=True),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version > 0",
            name="ck_msg_ingress_dead_letter_version_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_msg_ingress_dead_letter_platform_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(runtime_profile_key)) > 0",
            name="ck_msg_ingress_dead_letter_runtime_profile_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(ipc_command)) > 0",
            name="ck_msg_ingress_dead_letter_ipc_command_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(source_mode)) > 0",
            name="ck_msg_ingress_dead_letter_source_mode_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_msg_ingress_dead_letter_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_msg_ingress_dead_letter_dedupe_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(identifier_type)) > 0",
            name="ck_msg_ingress_dead_letter_identifier_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(reason_code)) > 0",
            name="ck_msg_ingress_dead_letter_reason_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_msg_ingress_dead_letter_status_nonempty",
        ),
        sa.CheckConstraint(
            "attempts > 0",
            name="ck_msg_ingress_dead_letter_attempts_positive",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            [f"{_SCHEMA}.messaging_ingress_event.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_source_event_id",
        "messaging_ingress_dead_letter",
        ["source_event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_platform",
        "messaging_ingress_dead_letter",
        ["platform"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_runtime_profile_key",
        "messaging_ingress_dead_letter",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_ipc_command",
        "messaging_ingress_dead_letter",
        ["ipc_command"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_event_type",
        "messaging_ingress_dead_letter",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_event_id",
        "messaging_ingress_dead_letter",
        ["event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_dedupe_key",
        "messaging_ingress_dead_letter",
        ["dedupe_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_identifier_value",
        "messaging_ingress_dead_letter",
        ["identifier_value"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_room_id",
        "messaging_ingress_dead_letter",
        ["room_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_sender",
        "messaging_ingress_dead_letter",
        ["sender"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_reason_code",
        "messaging_ingress_dead_letter",
        ["reason_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_status",
        "messaging_ingress_dead_letter",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_dead_letter_last_failed_at",
        "messaging_ingress_dead_letter",
        ["last_failed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_dead_letter_status_failed_at",
        "messaging_ingress_dead_letter",
        ["status", "last_failed_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "messaging_ingress_checkpoint",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("platform", postgresql.CITEXT(length=32), nullable=False),
        sa.Column("runtime_profile_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("checkpoint_key", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("checkpoint_value", postgresql.CITEXT(length=512), nullable=False),
        sa.Column(
            "provider_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "length(btrim(platform)) > 0",
            name="ck_msg_ingress_checkpoint_platform_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(runtime_profile_key)) > 0",
            name="ck_msg_ingress_checkpoint_runtime_profile_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(checkpoint_key)) > 0",
            name="ck_msg_ingress_checkpoint_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(checkpoint_value)) > 0",
            name="ck_msg_ingress_checkpoint_value_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "platform",
            "runtime_profile_key",
            "checkpoint_key",
            name="ux_msg_ingress_checkpoint_platform_profile_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_checkpoint_platform",
        "messaging_ingress_checkpoint",
        ["platform"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_checkpoint_runtime_profile_key",
        "messaging_ingress_checkpoint",
        ["runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_messaging_ingress_checkpoint_checkpoint_key",
        "messaging_ingress_checkpoint",
        ["checkpoint_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_msg_ingress_checkpoint_platform_profile",
        "messaging_ingress_checkpoint",
        ["platform", "runtime_profile_key"],
        unique=False,
        schema=_SCHEMA,
    )

    for platform, table_name in _LEGACY_DEDUP_TABLES:
        _backfill_legacy_dedup(platform, table_name)

    for platform, table_name, ipc_command, source_mode, identifier_type in _LEGACY_DEAD_LETTER_TABLES:
        _backfill_legacy_dead_letter(
            platform,
            table_name,
            ipc_command,
            source_mode,
            identifier_type,
        )

    for _, table_name in _LEGACY_DEDUP_TABLES:
        _drop_legacy_table(table_name)

    for _, table_name, _, _, _ in _LEGACY_DEAD_LETTER_TABLES:
        _drop_legacy_table(table_name)


def downgrade() -> None:
    for platform, table_name in _LEGACY_DEDUP_TABLES:
        _create_legacy_dedup_table(platform=platform, table_name=table_name)
        _restore_legacy_dedup(platform=platform, table_name=table_name)

    for platform, table_name, _, _, _ in _LEGACY_DEAD_LETTER_TABLES:
        _create_legacy_dead_letter_table(platform=platform, table_name=table_name)
        _restore_legacy_dead_letter(platform=platform, table_name=table_name)

    op.drop_index(
        "ix_msg_ingress_checkpoint_platform_profile",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_checkpoint_checkpoint_key",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_checkpoint_runtime_profile_key",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_messaging_ingress_checkpoint_platform",
        table_name="messaging_ingress_checkpoint",
        schema=_SCHEMA,
    )
    op.drop_table("messaging_ingress_checkpoint", schema=_SCHEMA)

    op.drop_index(
        "ix_msg_ingress_dead_letter_status_failed_at",
        table_name="messaging_ingress_dead_letter",
        schema=_SCHEMA,
    )
    for index_name in (
        "ix_messaging_ingress_dead_letter_last_failed_at",
        "ix_messaging_ingress_dead_letter_status",
        "ix_messaging_ingress_dead_letter_reason_code",
        "ix_messaging_ingress_dead_letter_sender",
        "ix_messaging_ingress_dead_letter_room_id",
        "ix_messaging_ingress_dead_letter_identifier_value",
        "ix_messaging_ingress_dead_letter_dedupe_key",
        "ix_messaging_ingress_dead_letter_event_id",
        "ix_messaging_ingress_dead_letter_event_type",
        "ix_messaging_ingress_dead_letter_ipc_command",
        "ix_messaging_ingress_dead_letter_runtime_profile_key",
        "ix_messaging_ingress_dead_letter_platform",
        "ix_messaging_ingress_dead_letter_source_event_id",
    ):
        op.drop_index(
            index_name,
            table_name="messaging_ingress_dead_letter",
            schema=_SCHEMA,
        )
    op.drop_table("messaging_ingress_dead_letter", schema=_SCHEMA)

    op.drop_index(
        "ix_msg_ingress_dedup_expiry",
        table_name="messaging_ingress_dedup",
        schema=_SCHEMA,
    )
    for index_name in (
        "ix_messaging_ingress_dedup_expires_at",
        "ix_messaging_ingress_dedup_event_id",
        "ix_messaging_ingress_dedup_dedupe_key",
        "ix_messaging_ingress_dedup_event_type",
        "ix_messaging_ingress_dedup_runtime_profile_key",
        "ix_messaging_ingress_dedup_platform",
    ):
        op.drop_index(
            index_name,
            table_name="messaging_ingress_dedup",
            schema=_SCHEMA,
        )
    op.drop_table("messaging_ingress_dedup", schema=_SCHEMA)

    op.drop_index(
        "ix_msg_ingress_event_platform_profile_status",
        table_name="messaging_ingress_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_msg_ingress_event_status_lease",
        table_name="messaging_ingress_event",
        schema=_SCHEMA,
    )
    for index_name in (
        "ix_messaging_ingress_event_completed_at",
        "ix_messaging_ingress_event_lease_expires_at",
        "ix_messaging_ingress_event_status",
        "ix_messaging_ingress_event_received_at",
        "ix_messaging_ingress_event_sender",
        "ix_messaging_ingress_event_room_id",
        "ix_messaging_ingress_event_identifier_value",
        "ix_messaging_ingress_event_dedupe_key",
        "ix_messaging_ingress_event_event_id",
        "ix_messaging_ingress_event_event_type",
        "ix_messaging_ingress_event_source_mode",
        "ix_messaging_ingress_event_ipc_command",
        "ix_messaging_ingress_event_runtime_profile_key",
        "ix_messaging_ingress_event_platform",
    ):
        op.drop_index(
            index_name,
            table_name="messaging_ingress_event",
            schema=_SCHEMA,
        )
    op.drop_table("messaging_ingress_event", schema=_SCHEMA)
