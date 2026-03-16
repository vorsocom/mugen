"""Provides a domain entity for the TaxonomyDomain DB model."""

from __future__ import annotations

__all__ = ["TaxonomyDomainDE"]

from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class TaxonomyDomainDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn taxonomy domain model."""

    code: str | None = None
    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    categories: Sequence["TaxonomyCategoryDE"] | None = None  # type: ignore
