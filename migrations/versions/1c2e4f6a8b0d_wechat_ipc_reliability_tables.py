"""wechat ipc reliability tables

Revision ID: 1c2e4f6a8b0d
Revises: fbd3a1e7c5d9
Create Date: 2026-03-05 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1c2e4f6a8b0d"
down_revision: Union[str, Sequence[str], None] = "fbd3a1e7c5d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.create_table(
        "wechat_event_dedup",
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
        sa.Column(
            "event_type",
            postgresql.CITEXT(length=64),
            nullable=False,
        ),
        sa.Column(
            "dedupe_key",
            postgresql.CITEXT(length=255),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.CITEXT(length=255),
            nullable=True,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_wechat_event_dedup_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(dedupe_key)) > 0",
            name="ck_wechat_event_dedup_key_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_type",
            "dedupe_key",
            name="ux_wechat_event_dedup_event_type_key",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_event_dedup_event_type",
        "wechat_event_dedup",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_event_dedup_dedupe_key",
        "wechat_event_dedup",
        ["dedupe_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_event_dedup_event_id",
        "wechat_event_dedup",
        ["event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_event_dedup_expiry",
        "wechat_event_dedup",
        ["event_type", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_event_dedup_expires_at",
        "wechat_event_dedup",
        ["expires_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "wechat_event_dead_letter",
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
        sa.Column(
            "event_type",
            postgresql.CITEXT(length=64),
            nullable=False,
        ),
        sa.Column(
            "dedupe_key",
            postgresql.CITEXT(length=255),
            nullable=True,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "reason_code",
            postgresql.CITEXT(length=128),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            postgresql.CITEXT(length=1024),
            nullable=True,
        ),
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
        sa.Column(
            "first_failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_wechat_dead_letter_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(reason_code)) > 0",
            name="ck_wechat_dead_letter_reason_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_wechat_dead_letter_status_nonempty",
        ),
        sa.CheckConstraint(
            "attempts > 0",
            name="ck_wechat_dead_letter_attempts_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_dead_letter_event_type",
        "wechat_event_dead_letter",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_dead_letter_dedupe_key",
        "wechat_event_dead_letter",
        ["dedupe_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_dead_letter_reason_code",
        "wechat_event_dead_letter",
        ["reason_code"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_dead_letter_status",
        "wechat_event_dead_letter",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_dead_letter_last_failed_at",
        "wechat_event_dead_letter",
        ["last_failed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_wechat_dead_letter_status_failed_at",
        "wechat_event_dead_letter",
        ["status", "last_failed_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wechat_dead_letter_status_failed_at",
        table_name="wechat_event_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_dead_letter_last_failed_at",
        table_name="wechat_event_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_dead_letter_status",
        table_name="wechat_event_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_dead_letter_reason_code",
        table_name="wechat_event_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_dead_letter_dedupe_key",
        table_name="wechat_event_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_dead_letter_event_type",
        table_name="wechat_event_dead_letter",
        schema=_SCHEMA,
    )
    op.drop_table("wechat_event_dead_letter", schema=_SCHEMA)

    op.drop_index(
        "ix_wechat_event_dedup_expires_at",
        table_name="wechat_event_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_event_dedup_expiry",
        table_name="wechat_event_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_event_dedup_event_id",
        table_name="wechat_event_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_event_dedup_dedupe_key",
        table_name="wechat_event_dedup",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_wechat_event_dedup_event_type",
        table_name="wechat_event_dedup",
        schema=_SCHEMA,
    )
    op.drop_table("wechat_event_dedup", schema=_SCHEMA)
