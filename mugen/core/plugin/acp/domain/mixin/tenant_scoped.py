"""Provides a domain entity for tenant scoping."""

__all__ = ["TenantScopedDEMixin"]

import uuid
from dataclasses import dataclass
from typing import Type


@dataclass
class TenantScopedDEMixin:
    """A domain entity for tenant scoping."""

    tenant_id: uuid.UUID | None = None

    tenant: Type["TenantDE"] | None = None  # type: ignore
