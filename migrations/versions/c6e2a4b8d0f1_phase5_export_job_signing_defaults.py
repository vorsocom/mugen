"""phase5 export job signing defaults remediation

Revision ID: c6e2a4b8d0f1
Revises: b7c9d1e3f5a7
Create Date: 2026-02-26 17:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from migrations.schema_contract import resolve_runtime_schema
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c6e2a4b8d0f1"
down_revision: Union[str, Sequence[str], None] = "b7c9d1e3f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = resolve_runtime_schema()


def upgrade() -> None:
    op.add_column(
        "ops_reporting_export_job",
        sa.Column(
            "default_sign",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "ops_reporting_export_job",
        sa.Column(
            "default_signature_key_id",
            postgresql.CITEXT(length=128),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        "ck_ops_reporting_export_job__default_sig_key_id_nonempty",
        "ops_reporting_export_job",
        (
            "default_signature_key_id IS NULL OR "
            "length(btrim(default_signature_key_id)) > 0"
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_ops_reporting_export_job__default_sig_key_id_nonempty",
        "ops_reporting_export_job",
        schema=_SCHEMA,
    )
    op.drop_column(
        "ops_reporting_export_job",
        "default_signature_key_id",
        schema=_SCHEMA,
    )
    op.drop_column(
        "ops_reporting_export_job",
        "default_sign",
        schema=_SCHEMA,
    )
