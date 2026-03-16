"""Provides a domain entity for the TaxonomyCategory DB model."""

from __future__ import annotations

__all__ = ["TaxonomyCategoryDE"]

import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class TaxonomyCategoryDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn taxonomy category model."""

    taxonomy_domain_id: uuid.UUID | None = None
    code: str | None = None
    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    domain: "TaxonomyDomainDE" | None = None  # type: ignore
    subcategories: Sequence["TaxonomySubcategoryDE"] | None = None  # type: ignore
