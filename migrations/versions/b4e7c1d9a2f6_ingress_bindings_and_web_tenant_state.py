"""ingress bindings and web tenant state

Revision ID: b4e7c1d9a2f6
Revises: 3d9a5c7b1e2f, fb3d7a1c9e24
Create Date: 2026-03-05 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b4e7c1d9a2f6"
down_revision: Union[str, Sequence[str], None] = (
    "3d9a5c7b1e2f",
    "fb3d7a1c9e24",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()
_GLOBAL_TENANT_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.create_table(
        "channel_orchestration_ingress_binding",
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
        sa.Column("channel_profile_id", sa.Uuid(), nullable=True),
        sa.Column("channel_key", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("identifier_type", postgresql.CITEXT(length=64), nullable=False),
        sa.Column("identifier_value", postgresql.CITEXT(length=255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            [f"{_SCHEMA}.admin_tenant.id"],
            ondelete="RESTRICT",
            name="fk_chorch_ingress_binding_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["channel_profile_id"],
            [f"{_SCHEMA}.channel_orchestration_channel_profile.id"],
            ondelete="SET NULL",
            name="fk_chorch_ingress_binding_profile",
        ),
        sa.CheckConstraint(
            "length(btrim(channel_key)) > 0",
            name="ck_chorch_ingress_binding__channel_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(identifier_type)) > 0",
            name="ck_chorch_ingress_binding__identifier_type_nonempty",
        ),
        sa.CheckConstraint(
            "length(btrim(identifier_value)) > 0",
            name="ck_chorch_ingress_binding__identifier_value_nonempty",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chorch_ingress_binding"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            name="ux_chorch_ingress_binding__tenant_id_id",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_ingress_binding__tenant_channel_identifier_active",
        "channel_orchestration_ingress_binding",
        [
            "tenant_id",
            "channel_key",
            "identifier_type",
            "identifier_value",
            "is_active",
        ],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_chorch_ingress_binding__channel_identifier_active",
        "channel_orchestration_ingress_binding",
        [
            "channel_key",
            "identifier_type",
            "identifier_value",
            "is_active",
        ],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_chorch_ingress_binding__tci_active_unique",
        "channel_orchestration_ingress_binding",
        [
            "tenant_id",
            "channel_key",
            "identifier_type",
            "identifier_value",
        ],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("is_active = true"),
    )

    op.add_column(
        "web_conversation_state",
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            nullable=True,
            server_default=sa.text(f"'{_GLOBAL_TENANT_ID}'::uuid"),
        ),
        schema=_SCHEMA,
    )
    op.execute(
        f"UPDATE {_SCHEMA}.web_conversation_state "
        f"SET tenant_id = '{_GLOBAL_TENANT_ID}'::uuid "
        "WHERE tenant_id IS NULL"
    )
    op.create_foreign_key(
        "fk_web_conversation_state_tenant",
        source_table="web_conversation_state",
        referent_table="admin_tenant",
        local_cols=["tenant_id"],
        remote_cols=["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_web_conversation_state_tenant_id",
        "web_conversation_state",
        ["tenant_id"],
        unique=False,
        schema=_SCHEMA,
    )
    op.alter_column(
        "web_conversation_state",
        "tenant_id",
        nullable=False,
        server_default=None,
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "web_conversation_state",
        "tenant_id",
        nullable=True,
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_web_conversation_state_tenant_id",
        table_name="web_conversation_state",
        schema=_SCHEMA,
    )
    op.drop_constraint(
        "fk_web_conversation_state_tenant",
        "web_conversation_state",
        type_="foreignkey",
        schema=_SCHEMA,
    )
    op.drop_column("web_conversation_state", "tenant_id", schema=_SCHEMA)

    op.drop_index(
        "ux_chorch_ingress_binding__tci_active_unique",
        table_name="channel_orchestration_ingress_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_ingress_binding__channel_identifier_active",
        table_name="channel_orchestration_ingress_binding",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_chorch_ingress_binding__tenant_channel_identifier_active",
        table_name="channel_orchestration_ingress_binding",
        schema=_SCHEMA,
    )
    op.drop_table("channel_orchestration_ingress_binding", schema=_SCHEMA)
