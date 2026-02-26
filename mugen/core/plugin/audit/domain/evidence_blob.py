"""Provides a domain entity for EvidenceBlob DB model."""

__all__ = ["EvidenceBlobDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


# pylint: disable=too-many-instance-attributes
@dataclass
class EvidenceBlobDE(BaseDE):
    """A domain entity for metadata-first evidence blobs."""

    tenant_id: uuid.UUID | None = None

    trace_id: str | None = None
    source_plugin: str | None = None
    subject_namespace: str | None = None
    subject_id: uuid.UUID | None = None

    storage_uri: str | None = None
    content_hash: str | None = None
    hash_alg: str | None = None
    content_length: int | None = None

    immutability: str | None = None
    verification_status: str | None = None
    verified_at: datetime | None = None
    verified_by_user_id: uuid.UUID | None = None

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

    purged_at: datetime | None = None
    purged_by_user_id: uuid.UUID | None = None
    purge_reason: str | None = None

    meta: dict[str, Any] | None = None
