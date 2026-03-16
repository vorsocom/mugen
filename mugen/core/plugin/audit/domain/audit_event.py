"""Provides a domain entity for the AuditEvent DB model."""

__all__ = ["AuditEventDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


# pylint: disable=too-many-instance-attributes
@dataclass
class AuditEventDE(BaseDE):
    """A domain entity for append-only audit events."""

    tenant_id: uuid.UUID | None = None
    actor_id: uuid.UUID | None = None

    entity_set: str | None = None
    entity: str | None = None
    entity_id: uuid.UUID | None = None

    operation: str | None = None
    action_name: str | None = None
    occurred_at: datetime | None = None
    outcome: str | None = None

    request_id: str | None = None
    correlation_id: str | None = None
    source_plugin: str | None = None

    changed_fields: list[str] | None = None
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None

    scope_key: str | None = None
    scope_seq: int | None = None
    prev_entry_hash: str | None = None
    entry_hash: str | None = None
    hash_alg: str | None = None
    hash_key_id: str | None = None
    before_snapshot_hash: str | None = None
    after_snapshot_hash: str | None = None
    sealed_at: datetime | None = None

    retention_until: datetime | None = None
    redaction_due_at: datetime | None = None
    redacted_at: datetime | None = None
    redaction_reason: str | None = None
    legal_hold_at: datetime | None = None
    legal_hold_until: datetime | None = None
    legal_hold_by_user_id: uuid.UUID | None = None
    legal_hold_reason: str | None = None
    legal_hold_released_at: datetime | None = None
    legal_hold_released_by_user_id: uuid.UUID | None = None
    legal_hold_release_reason: str | None = None
    tombstoned_at: datetime | None = None
    tombstoned_by_user_id: uuid.UUID | None = None
    tombstone_reason: str | None = None
    purge_due_at: datetime | None = None
