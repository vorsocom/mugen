"""Provides a domain entity for the VerificationCriterion DB model."""

from __future__ import annotations

__all__ = ["VerificationCriterionDE"]

from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class VerificationCriterionDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for generic verification checklist criteria."""

    code: str | None = None
    name: str | None = None
    description: str | None = None
    verification_type: str | None = None
    is_required: bool | None = None
    sort_order: int | None = None
    attributes: dict[str, Any] | None = None

    checks: Sequence["VendorVerificationCheckDE"] | None = None  # type: ignore
