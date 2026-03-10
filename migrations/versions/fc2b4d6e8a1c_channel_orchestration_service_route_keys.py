"""channel orchestration service route keys

Revision ID: fc2b4d6e8a1c
Revises: fb1c2d3e4f5a
Create Date: 2026-03-10 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fc2b4d6e8a1c"
down_revision: Union[str, Sequence[str], None] = "fb1c2d3e4f5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.add_column(
        "channel_orchestration_channel_profile",
        sa.Column(
            "service_route_default_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "channel_orchestration_ingress_binding",
        sa.Column(
            "service_route_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "channel_orchestration_conversation_state",
        sa.Column(
            "service_route_key",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )

    op.create_check_constraint(
        "ck_chorch_profile__service_route_default_nonempty_if_set",
        "channel_orchestration_channel_profile",
        (
            "service_route_default_key IS NULL OR "
            "length(btrim(service_route_default_key)) > 0"
        ),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_chorch_ingress_binding__service_route_nonempty_if_set",
        "channel_orchestration_ingress_binding",
        "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_chorch_state__service_route_nonempty_if_set",
        "channel_orchestration_conversation_state",
        "service_route_key IS NULL OR length(btrim(service_route_key)) > 0",
        schema=_SCHEMA,
    )

    op.create_index(
        "ix_chorch_profile__service_route_default_key",
        "channel_orchestration_channel_profile",
        ["service_route_default_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_ingress_binding__service_route_key",
        "channel_orchestration_ingress_binding",
        ["service_route_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_state__service_route_key",
        "channel_orchestration_conversation_state",
        ["service_route_key"],
        unique=False,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chorch_state__service_route_key",
        table_name="channel_orchestration_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_ingress_binding__service_route_key",
        table_name="channel_orchestration_ingress_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_profile__service_route_default_key",
        table_name="channel_orchestration_channel_profile",
        schema=_SCHEMA,
    )

    op.drop_constraint(
        "ck_chorch_state__service_route_nonempty_if_set",
        "channel_orchestration_conversation_state",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_chorch_ingress_binding__service_route_nonempty_if_set",
        "channel_orchestration_ingress_binding",
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "ck_chorch_profile__service_route_default_nonempty_if_set",
        "channel_orchestration_channel_profile",
        schema=_SCHEMA,
        type_="check",
    )

    op.drop_column(
        "channel_orchestration_conversation_state",
        "service_route_key",
        schema=_SCHEMA,
    )
    op.drop_column(
        "channel_orchestration_ingress_binding",
        "service_route_key",
        schema=_SCHEMA,
    )
    op.drop_column(
        "channel_orchestration_channel_profile",
        "service_route_default_key",
        schema=_SCHEMA,
    )
