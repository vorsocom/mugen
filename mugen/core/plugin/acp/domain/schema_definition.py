"""Provides a domain entity for the SchemaDefinition DB model."""

__all__ = ["SchemaDefinitionDE"]

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class SchemaDefinitionDE(BaseDE):
    """A domain entity for ACP schema definitions."""

    tenant_id: uuid.UUID | None = None

    key: str | None = None

    version: int | None = None

    title: str | None = None

    description: str | None = None

    schema_kind: str | None = None

    schema_json: dict[str, Any] | None = None

    status: str | None = None

    activated_at: datetime | None = None

    activated_by_user_id: uuid.UUID | None = None

    checksum_sha256: str | None = None

    attributes: dict[str, Any] | None = None
