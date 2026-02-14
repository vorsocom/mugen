"""Provides a domain entity for the UsageAllocation DB model."""

__all__ = ["UsageAllocationDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class UsageAllocationDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the billing UsageAllocation DB model."""

    usage_event_id: uuid.UUID | None = None
    entitlement_bucket_id: uuid.UUID | None = None

    allocated_quantity: int | None = None

    external_ref: str | None = None
    attributes: dict[str, Any] | None = None

    usage_event: "UsageEventDE | None" = None  # type: ignore
    entitlement_bucket: "EntitlementBucketDE | None" = None  # type: ignore
