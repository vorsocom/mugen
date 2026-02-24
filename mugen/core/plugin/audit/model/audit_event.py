"""Provides an ORM for audit events."""

__all__ = ["AuditEvent"]

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Uuid
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase


# pylint: disable=too-few-public-methods
class AuditEvent(ModelBase):
    """Append-only audit event log entry."""

    __tablename__ = "audit_event"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
        index=True,
    )

    entity_set: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)

    operation: Mapped[str] = mapped_column(CITEXT(64), nullable=False, index=True)
    action_name: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa_text("now()"),
        index=True,
    )
    outcome: Mapped[str] = mapped_column(CITEXT(32), nullable=False, index=True)

    request_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    correlation_id: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    source_plugin: Mapped[str] = mapped_column(CITEXT(128), nullable=False, index=True)

    changed_fields: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    before_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    scope_key: Mapped[str] = mapped_column(CITEXT(256), nullable=False, index=True)
    scope_seq: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )
    prev_entry_hash: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)
    entry_hash: Mapped[str | None] = mapped_column(
        CITEXT(128),
        nullable=True,
        index=True,
    )
    hash_alg: Mapped[str] = mapped_column(
        CITEXT(64),
        nullable=False,
        server_default=sa_text("'hmac-sha256'"),
    )
    hash_key_id: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)
    before_snapshot_hash: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)
    after_snapshot_hash: Mapped[str | None] = mapped_column(CITEXT(128), nullable=True)
    sealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    redaction_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    redaction_reason: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    legal_hold_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    legal_hold_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    legal_hold_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    legal_hold_reason: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    legal_hold_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    legal_hold_released_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    legal_hold_release_reason: Mapped[str | None] = mapped_column(
        CITEXT(255),
        nullable=True,
    )
    tombstoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    tombstoned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        nullable=True,
    )
    tombstone_reason: Mapped[str | None] = mapped_column(CITEXT(255), nullable=True)
    purge_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    __table_args__ = (
        Index(
            "ix_audit_event__entity_lookup",
            "entity_set",
            "entity_id",
            "occurred_at",
        ),
        Index(
            "ux_audit_event__scope_seq",
            "scope_key",
            "scope_seq",
            unique=True,
        ),
        {"schema": "mugen"},
    )

    def __repr__(self) -> str:
        return f"AuditEvent(id={self.id!r})"
