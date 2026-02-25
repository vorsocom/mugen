"""Provides a domain entity for the DedupRecord DB model."""

__all__ = ["DedupRecordDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class DedupRecordDE(BaseDE):
    """A domain entity for shared idempotency ledger records."""

    tenant_id: uuid.UUID | None = None

    scope: str | None = None

    idempotency_key: str | None = None

    request_hash: str | None = None

    status: str | None = None

    result_ref: str | None = None

    response_code: int | None = None

    response_payload: Any | None = None

    error_code: str | None = None

    error_message: str | None = None

    owner_instance: str | None = None

    lease_expires_at: datetime | None = None

    expires_at: datetime | None = None
