"""channel profile runtime profile key

Revision ID: 4b7d2e1f9a6c
Revises: b4e7c1d9a2f6
Create Date: 2026-03-07 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "4b7d2e1f9a6c"
down_revision: Union[str, Sequence[str], None] = "b4e7c1d9a2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_PROFILED_CHANNELS = (
    "line",
    "matrix",
    "signal",
    "telegram",
    "wechat",
    "whatsapp",
)
_PROFILED_CHANNELS_SQL = ", ".join(f"'{channel}'" for channel in _PROFILED_CHANNELS)


def upgrade() -> None:
    op.add_column(
        "channel_orchestration_channel_profile",
        sa.Column(
            "runtime_profile_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {_SCHEMA}.channel_orchestration_channel_profile
            SET runtime_profile_key = 'default'
            WHERE runtime_profile_key IS NULL
              AND lower(channel_key) IN ({_PROFILED_CHANNELS_SQL})
            """
        )
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


def downgrade() -> None:
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
