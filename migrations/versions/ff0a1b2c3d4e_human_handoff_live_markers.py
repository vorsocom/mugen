"""human handoff live update markers

Revision ID: ff0a1b2c3d4e
Revises: fe9a8b7c6d5e
Create Date: 2026-06-02 12:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema

# revision identifiers, used by Alembic.
revision: str = "ff0a1b2c3d4e"
down_revision: Union[str, Sequence[str], None] = "fe9a8b7c6d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.add_column(
        "channel_orchestration_human_handoff_session",
        sa.Column("last_user_message_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "channel_orchestration_human_handoff_session",
        sa.Column("last_transcript_sequence_no", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_chorch_handoff__last_transcript_seq_nonnegative",
        "channel_orchestration_human_handoff_session",
        (
            "last_transcript_sequence_no IS NULL OR "
            "last_transcript_sequence_no >= 0"
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_handoff__last_user_message_at",
        "channel_orchestration_human_handoff_session",
        ["last_user_message_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_handoff__last_transcript_sequence_no",
        "channel_orchestration_human_handoff_session",
        ["last_transcript_sequence_no"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chorch_handoff__last_transcript_sequence_no",
        table_name="channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_handoff__last_user_message_at",
        table_name="channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "ck_chorch_handoff__last_transcript_seq_nonnegative",
        "channel_orchestration_human_handoff_session",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_column(
        "channel_orchestration_human_handoff_session",
        "last_transcript_sequence_no",
        schema=_SCHEMA,
    )
    op.drop_column(
        "channel_orchestration_human_handoff_session",
        "last_user_message_at",
        schema=_SCHEMA,
    )
