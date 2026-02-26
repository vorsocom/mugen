"""Canonicalize ops_governance resource_type values and enforce checks.

Revision ID: f6d9c2b4a1e7
Revises: f1a9b7c3d5e2
Create Date: 2026-02-26 13:20:00.000000

"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f6d9c2b4a1e7"
down_revision: Union[str, Sequence[str], None] = "f1a9b7c3d5e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"
_RETENTION_CLASS_TABLE = "ops_governance_retention_class"
_LEGAL_HOLD_TABLE = "ops_governance_legal_hold"

_RETENTION_CLASS_RESOURCE_TYPE_CHECK = (
    "ck_ops_gov_retention_class__resource_type_canonical"
)
_LEGAL_HOLD_RESOURCE_TYPE_CHECK = "ck_ops_gov_legal_hold__resource_type_canonical"


def _guard_active_canonical_conflicts() -> None:
    if context.is_offline_mode():
        return

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"""
            WITH normalized AS (
                SELECT
                    tenant_id::text AS tenant_id,
                    CASE
                        WHEN lower(replace(resource_type::text, '-', '_'))
                            IN ('audit', 'auditevent', 'audit_event')
                        THEN 'audit_event'
                        WHEN lower(replace(resource_type::text, '-', '_'))
                            IN ('evidence', 'evidenceblob', 'evidence_blob')
                        THEN 'evidence_blob'
                        ELSE lower(replace(resource_type::text, '-', '_'))
                    END AS canonical_type
                FROM {_SCHEMA}.{_RETENTION_CLASS_TABLE}
                WHERE is_active IS TRUE
            )
            SELECT
                tenant_id,
                canonical_type,
                COUNT(*) AS active_count
            FROM normalized
            WHERE canonical_type IN ('audit_event', 'evidence_blob')
            GROUP BY tenant_id, canonical_type
            HAVING COUNT(*) > 1
            ORDER BY tenant_id, canonical_type
            LIMIT 10
            """
        )
    ).mappings().all()

    if not rows:
        return

    sample = ", ".join(
        f"{row['tenant_id']}/{row['canonical_type']}({row['active_count']})"
        for row in rows
    )
    raise RuntimeError(
        "Cannot canonicalize active retention class resource_type values. "
        "Resolve duplicate active rows that collapse to the same canonical type "
        f"before migration. Examples: {sample}"
    )


def _canonicalize_resource_type_aliases(table_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE {_SCHEMA}.{table_name}
            SET resource_type = 'audit_event'
            WHERE lower(replace(resource_type::text, '-', '_'))
                IN ('audit', 'auditevent', 'audit_event')
                AND resource_type::text <> 'audit_event'
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {_SCHEMA}.{table_name}
            SET resource_type = 'evidence_blob'
            WHERE lower(replace(resource_type::text, '-', '_'))
                IN ('evidence', 'evidenceblob', 'evidence_blob')
                AND resource_type::text <> 'evidence_blob'
            """
        )
    )


def _guard_unknown_resource_types(table_name: str) -> None:
    if context.is_offline_mode():
        return

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"""
            SELECT DISTINCT resource_type::text AS resource_type
            FROM {_SCHEMA}.{table_name}
            WHERE resource_type::text NOT IN ('audit_event', 'evidence_blob')
            ORDER BY resource_type::text
            LIMIT 10
            """
        )
    ).mappings().all()

    if not rows:
        return

    sample = ", ".join(row["resource_type"] for row in rows)
    raise RuntimeError(
        f"Cannot enforce canonical resource_type values on {table_name}. "
        "Unsupported values remain after canonicalization. "
        f"Examples: {sample}"
    )


def upgrade() -> None:
    """Canonicalize resource_type values and enforce canonical checks."""
    _guard_active_canonical_conflicts()

    _canonicalize_resource_type_aliases(_RETENTION_CLASS_TABLE)
    _canonicalize_resource_type_aliases(_LEGAL_HOLD_TABLE)

    _guard_unknown_resource_types(_RETENTION_CLASS_TABLE)
    _guard_unknown_resource_types(_LEGAL_HOLD_TABLE)

    op.create_check_constraint(
        _RETENTION_CLASS_RESOURCE_TYPE_CHECK,
        _RETENTION_CLASS_TABLE,
        "resource_type::text IN ('audit_event', 'evidence_blob')",
        schema=_SCHEMA,
    )
    op.create_check_constraint(
        _LEGAL_HOLD_RESOURCE_TYPE_CHECK,
        _LEGAL_HOLD_TABLE,
        "resource_type::text IN ('audit_event', 'evidence_blob')",
        schema=_SCHEMA,
    )


def downgrade() -> None:
    """Drop canonical resource_type checks."""
    op.drop_constraint(
        _LEGAL_HOLD_RESOURCE_TYPE_CHECK,
        _LEGAL_HOLD_TABLE,
        schema=_SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        _RETENTION_CLASS_RESOURCE_TYPE_CHECK,
        _RETENTION_CLASS_TABLE,
        schema=_SCHEMA,
        type_="check",
    )
