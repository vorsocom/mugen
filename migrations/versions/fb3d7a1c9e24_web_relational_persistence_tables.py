"""web relational persistence tables

Revision ID: fb3d7a1c9e24
Revises: f9a3c1d5e7b2
Create Date: 2026-02-26 23:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fb3d7a1c9e24"
down_revision: Union[str, Sequence[str], None] = "f9a3c1d5e7b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def _create_base_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "web_conversation_state",
        *_create_base_columns(),
        sa.Column("conversation_id", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("owner_user_id", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("stream_generation", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "stream_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "next_event_id",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_conversation_state_conversation_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(owner_user_id)) > 0",
            name="ck_web_conversation_state_owner_user_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(stream_generation)) > 0",
            name="ck_web_conversation_state_stream_generation_nonempty",
        ),
        sa.CheckConstraint(
            "next_event_id > 0",
            name="ck_web_conversation_state_next_event_id_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            name="ux_web_conversation_state_conversation_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_state_conversation_id",
        "web_conversation_state",
        ["conversation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_state_owner_user_id",
        "web_conversation_state",
        ["owner_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_state_stream_generation",
        "web_conversation_state",
        ["stream_generation"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_state_owner_conversation",
        "web_conversation_state",
        ["owner_user_id", "conversation_id"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "web_conversation_event",
        *_create_base_columns(),
        sa.Column("conversation_id", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("stream_generation", postgresql.CITEXT(length=64), nullable=False),
        sa.Column(
            "stream_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_conversation_event_conversation_id_nonempty",
        ),
        sa.CheckConstraint(
            "event_id > 0",
            name="ck_web_conversation_event_event_id_positive",
        ),
        sa.CheckConstraint(
            "length(btrim(event_type)) > 0",
            name="ck_web_conversation_event_event_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(stream_generation)) > 0",
            name="ck_web_conversation_event_stream_generation_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "event_id",
            name="ux_web_conversation_event_conversation_id_event_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_event_conversation_id",
        "web_conversation_event",
        ["conversation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_event_event_type",
        "web_conversation_event",
        ["event_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_event_conversation_event_id",
        "web_conversation_event",
        ["conversation_id", "event_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_conversation_event_conversation_created_at",
        "web_conversation_event",
        ["conversation_id", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "web_queue_job",
        *_create_base_columns(),
        sa.Column("job_id", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("conversation_id", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("sender", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("message_type", postgresql.CITEXT(length=32), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.CITEXT(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            postgresql.CITEXT(length=2048),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "client_message_id",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        sa.CheckConstraint(
            "length(btrim(job_id)) > 0",
            name="ck_web_queue_job_job_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_queue_job_conversation_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(sender)) > 0",
            name="ck_web_queue_job_sender_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(message_type)) > 0",
            name="ck_web_queue_job_message_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(status)) > 0",
            name="ck_web_queue_job_status_nonempty",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_web_queue_job_attempts_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="ux_web_queue_job_job_id"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_job_id",
        "web_queue_job",
        ["job_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_conversation_id",
        "web_queue_job",
        ["conversation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_sender",
        "web_queue_job",
        ["sender"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_message_type",
        "web_queue_job",
        ["message_type"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_status",
        "web_queue_job",
        ["status"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_lease_expires_at",
        "web_queue_job",
        ["lease_expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_completed_at",
        "web_queue_job",
        ["completed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_client_message_id",
        "web_queue_job",
        ["client_message_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_status_lease",
        "web_queue_job",
        ["status", "lease_expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_queue_job_conversation_created",
        "web_queue_job",
        ["conversation_id", "created_at"],
        unique=False,
        schema=_SCHEMA,
    )

    op.create_table(
        "web_media_token",
        *_create_base_columns(),
        sa.Column("token", postgresql.CITEXT(length=128), nullable=False),
        sa.Column("owner_user_id", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("conversation_id", postgresql.CITEXT(length=255), nullable=False),
        sa.Column("file_path", postgresql.CITEXT(length=2048), nullable=False),
        sa.Column("mime_type", postgresql.CITEXT(length=255), nullable=True),
        sa.Column("filename", postgresql.CITEXT(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(token)) > 0",
            name="ck_web_media_token_token_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(owner_user_id)) > 0",
            name="ck_web_media_token_owner_user_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(conversation_id)) > 0",
            name="ck_web_media_token_conversation_id_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(file_path)) > 0",
            name="ck_web_media_token_file_path_nonempty",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="ux_web_media_token_token"),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_media_token_token",
        "web_media_token",
        ["token"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_media_token_owner_user_id",
        "web_media_token",
        ["owner_user_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_media_token_conversation_id",
        "web_media_token",
        ["conversation_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_media_token_expires_at",
        "web_media_token",
        ["expires_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_web_media_token_owner_expires",
        "web_media_token",
        ["owner_user_id", "expires_at"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_web_media_token_owner_expires",
        table_name="web_media_token",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_media_token_expires_at",
        table_name="web_media_token",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_media_token_conversation_id",
        table_name="web_media_token",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_media_token_owner_user_id",
        table_name="web_media_token",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_media_token_token",
        table_name="web_media_token",
        schema=_SCHEMA,
    )
    op.drop_table("web_media_token", schema=_SCHEMA)

    op.drop_index(
        "ix_web_queue_job_conversation_created",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_status_lease",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_client_message_id",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_completed_at",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_lease_expires_at",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_status",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_message_type",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_sender",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_conversation_id",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_queue_job_job_id",
        table_name="web_queue_job",
        schema=_SCHEMA,
    )
    op.drop_table("web_queue_job", schema=_SCHEMA)

    op.drop_index(
        "ix_web_conversation_event_conversation_created_at",
        table_name="web_conversation_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_event_conversation_event_id",
        table_name="web_conversation_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_event_event_type",
        table_name="web_conversation_event",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_event_conversation_id",
        table_name="web_conversation_event",
        schema=_SCHEMA,
    )
    op.drop_table("web_conversation_event", schema=_SCHEMA)

    op.drop_index(
        "ix_web_conversation_state_owner_conversation",
        table_name="web_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_state_stream_generation",
        table_name="web_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_state_owner_user_id",
        table_name="web_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_state_conversation_id",
        table_name="web_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_table("web_conversation_state", schema=_SCHEMA)
