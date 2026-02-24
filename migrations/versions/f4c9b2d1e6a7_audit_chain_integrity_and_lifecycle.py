"""audit chain integrity and lifecycle controls

Revision ID: f4c9b2d1e6a7
Revises: 8f0c1d2e3a4b
Create Date: 2026-02-24 15:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# pylint: disable=no-member

# revision identifiers, used by Alembic.
revision: str = "f4c9b2d1e6a7"
down_revision: Union[str, None] = "8f0c1d2e3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMA = "mugen"


def upgrade() -> None:
    op.add_column(
        "audit_event",
        sa.Column("scope_key", postgresql.CITEXT(length=256), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("scope_seq", sa.BigInteger(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("prev_entry_hash", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("entry_hash", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column(
            "hash_alg",
            postgresql.CITEXT(length=64),
            server_default=sa.text("'hmac-sha256'"),
            nullable=False,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("hash_key_id", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("before_snapshot_hash", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("after_snapshot_hash", postgresql.CITEXT(length=128), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("legal_hold_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("legal_hold_until", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("legal_hold_by_user_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("legal_hold_reason", postgresql.CITEXT(length=255), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("legal_hold_released_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("legal_hold_released_by_user_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column(
            "legal_hold_release_reason",
            postgresql.CITEXT(length=255),
            nullable=True,
        ),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("tombstoned_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("tombstoned_by_user_id", sa.Uuid(), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("tombstone_reason", postgresql.CITEXT(length=255), nullable=True),
        schema=_SCHEMA,
    )
    op.add_column(
        "audit_event",
        sa.Column("purge_due_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )

    op.create_table(
        "audit_chain_head",
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
        sa.Column("scope_key", postgresql.CITEXT(length=256), nullable=False),
        sa.Column("last_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "last_entry_hash",
            postgresql.CITEXT(length=128),
            server_default=sa.text("'0000000000000000000000000000000000000000000000000000000000000000'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_chain_head"),
        sa.UniqueConstraint("scope_key", name="ux_audit_chain_head__scope_key"),
        schema=_SCHEMA,
    )

    op.execute(
        """
        UPDATE mugen.audit_event
           SET scope_key = COALESCE(tenant_id::text, 'global')
                        || ':' || lower(entity_set::text)
         WHERE scope_key IS NULL;
        """
    )
    op.execute(
        """
        UPDATE mugen.audit_event
           SET before_snapshot_hash = encode(
                   digest(COALESCE(before_snapshot::text, 'null'), 'sha256'),
                   'hex'
               )
         WHERE before_snapshot_hash IS NULL;
        """
    )
    op.execute(
        """
        UPDATE mugen.audit_event
           SET after_snapshot_hash = encode(
                   digest(COALESCE(after_snapshot::text, 'null'), 'sha256'),
                   'hex'
               )
         WHERE after_snapshot_hash IS NULL;
        """
    )
    op.alter_column("audit_event", "scope_key", nullable=False, schema=_SCHEMA)

    op.create_index(
        op.f("ix_mugen_audit_event_scope_key"),
        "audit_event",
        ["scope_key"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_scope_seq"),
        "audit_event",
        ["scope_seq"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_entry_hash"),
        "audit_event",
        ["entry_hash"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_sealed_at"),
        "audit_event",
        ["sealed_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_legal_hold_at"),
        "audit_event",
        ["legal_hold_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_legal_hold_released_at"),
        "audit_event",
        ["legal_hold_released_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_tombstoned_at"),
        "audit_event",
        ["tombstoned_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        op.f("ix_mugen_audit_event_purge_due_at"),
        "audit_event",
        ["purge_due_at"],
        unique=False,
        schema=_SCHEMA,
    )
    op.create_index(
        "ux_audit_event__scope_seq",
        "audit_event",
        ["scope_key", "scope_seq"],
        unique=True,
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_audit_event__redact_due_work",
        "audit_event",
        ["redaction_due_at", "id"],
        unique=False,
        schema=_SCHEMA,
        postgresql_where=sa.text(
            "redacted_at IS NULL AND legal_hold_at IS NULL AND redaction_due_at IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_audit_event__tombstone_due_work",
        "audit_event",
        ["retention_until", "id"],
        unique=False,
        schema=_SCHEMA,
        postgresql_where=sa.text(
            "tombstoned_at IS NULL AND legal_hold_at IS NULL AND retention_until IS NOT NULL"
        ),
    )
    op.create_index(
        "ix_audit_event__purge_due_work",
        "audit_event",
        ["purge_due_at", "id"],
        unique=False,
        schema=_SCHEMA,
        postgresql_where=sa.text(
            "tombstoned_at IS NOT NULL AND legal_hold_at IS NULL AND purge_due_at IS NOT NULL"
        ),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION mugen.tg_guard_audit_event_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF
                NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR
                NEW.actor_id IS DISTINCT FROM OLD.actor_id OR
                NEW.entity_set IS DISTINCT FROM OLD.entity_set OR
                NEW.entity IS DISTINCT FROM OLD.entity OR
                NEW.entity_id IS DISTINCT FROM OLD.entity_id OR
                NEW.operation IS DISTINCT FROM OLD.operation OR
                NEW.action_name IS DISTINCT FROM OLD.action_name OR
                NEW.occurred_at IS DISTINCT FROM OLD.occurred_at OR
                NEW.outcome IS DISTINCT FROM OLD.outcome OR
                NEW.request_id IS DISTINCT FROM OLD.request_id OR
                NEW.correlation_id IS DISTINCT FROM OLD.correlation_id OR
                NEW.source_plugin IS DISTINCT FROM OLD.source_plugin OR
                NEW.changed_fields IS DISTINCT FROM OLD.changed_fields OR
                NEW.meta IS DISTINCT FROM OLD.meta OR
                NEW.retention_until IS DISTINCT FROM OLD.retention_until OR
                NEW.redaction_due_at IS DISTINCT FROM OLD.redaction_due_at
            THEN
                RAISE EXCEPTION
                    'audit_event immutable business fields cannot be updated'
                    USING ERRCODE = 'P0001';
            END IF;

            IF
                NEW.scope_key IS DISTINCT FROM OLD.scope_key OR
                NEW.scope_seq IS DISTINCT FROM OLD.scope_seq OR
                NEW.prev_entry_hash IS DISTINCT FROM OLD.prev_entry_hash OR
                NEW.entry_hash IS DISTINCT FROM OLD.entry_hash OR
                NEW.hash_alg IS DISTINCT FROM OLD.hash_alg OR
                NEW.hash_key_id IS DISTINCT FROM OLD.hash_key_id OR
                NEW.before_snapshot_hash IS DISTINCT FROM OLD.before_snapshot_hash OR
                NEW.after_snapshot_hash IS DISTINCT FROM OLD.after_snapshot_hash OR
                NEW.sealed_at IS DISTINCT FROM OLD.sealed_at
            THEN
                IF NOT (
                    OLD.sealed_at IS NULL AND
                    OLD.scope_seq IS NULL AND
                    OLD.entry_hash IS NULL AND
                    NEW.sealed_at IS NOT NULL AND
                    NEW.scope_seq IS NOT NULL AND
                    NEW.entry_hash IS NOT NULL
                ) THEN
                    RAISE EXCEPTION
                        'audit_event chain fields cannot be modified after sealing'
                        USING ERRCODE = 'P0001';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION mugen.tg_guard_audit_event_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.tombstoned_at IS NULL THEN
                RAISE EXCEPTION
                    'audit_event delete denied: row is not tombstoned'
                    USING ERRCODE = 'P0001';
            END IF;

            IF OLD.purge_due_at IS NULL OR OLD.purge_due_at > now() THEN
                RAISE EXCEPTION
                    'audit_event delete denied: purge window not reached'
                    USING ERRCODE = 'P0001';
            END IF;

            IF OLD.legal_hold_at IS NOT NULL AND OLD.legal_hold_released_at IS NULL THEN
                IF OLD.legal_hold_until IS NULL OR OLD.legal_hold_until > now() THEN
                    RAISE EXCEPTION
                        'audit_event delete denied: active legal hold'
                        USING ERRCODE = 'P0001';
                END IF;
            END IF;

            RETURN OLD;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE OR REPLACE TRIGGER tr_guard_audit_event_update
        BEFORE UPDATE ON mugen.audit_event
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_audit_event_update();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE TRIGGER tr_guard_audit_event_delete
        BEFORE DELETE ON mugen.audit_event
        FOR EACH ROW
        EXECUTE FUNCTION mugen.tg_guard_audit_event_delete();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_guard_audit_event_delete ON mugen.audit_event;")
    op.execute("DROP TRIGGER IF EXISTS tr_guard_audit_event_update ON mugen.audit_event;")
    op.execute("DROP FUNCTION IF EXISTS mugen.tg_guard_audit_event_delete();")
    op.execute("DROP FUNCTION IF EXISTS mugen.tg_guard_audit_event_update();")

    op.drop_index("ix_audit_event__purge_due_work", table_name="audit_event", schema=_SCHEMA)
    op.drop_index("ix_audit_event__tombstone_due_work", table_name="audit_event", schema=_SCHEMA)
    op.drop_index("ix_audit_event__redact_due_work", table_name="audit_event", schema=_SCHEMA)
    op.drop_index("ux_audit_event__scope_seq", table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_purge_due_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_tombstoned_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_legal_hold_released_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_legal_hold_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_sealed_at"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_entry_hash"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_scope_seq"), table_name="audit_event", schema=_SCHEMA)
    op.drop_index(op.f("ix_mugen_audit_event_scope_key"), table_name="audit_event", schema=_SCHEMA)

    op.drop_column("audit_event", "purge_due_at", schema=_SCHEMA)
    op.drop_column("audit_event", "tombstone_reason", schema=_SCHEMA)
    op.drop_column("audit_event", "tombstoned_by_user_id", schema=_SCHEMA)
    op.drop_column("audit_event", "tombstoned_at", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_release_reason", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_released_by_user_id", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_released_at", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_reason", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_by_user_id", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_until", schema=_SCHEMA)
    op.drop_column("audit_event", "legal_hold_at", schema=_SCHEMA)
    op.drop_column("audit_event", "sealed_at", schema=_SCHEMA)
    op.drop_column("audit_event", "after_snapshot_hash", schema=_SCHEMA)
    op.drop_column("audit_event", "before_snapshot_hash", schema=_SCHEMA)
    op.drop_column("audit_event", "hash_key_id", schema=_SCHEMA)
    op.drop_column("audit_event", "hash_alg", schema=_SCHEMA)
    op.drop_column("audit_event", "entry_hash", schema=_SCHEMA)
    op.drop_column("audit_event", "prev_entry_hash", schema=_SCHEMA)
    op.drop_column("audit_event", "scope_seq", schema=_SCHEMA)
    op.drop_column("audit_event", "scope_key", schema=_SCHEMA)

    op.drop_table("audit_chain_head", schema=_SCHEMA)
