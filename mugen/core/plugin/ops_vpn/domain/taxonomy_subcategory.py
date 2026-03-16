"""Provides a domain entity for the TaxonomySubcategory DB model."""

from __future__ import annotations

__all__ = ["TaxonomySubcategoryDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class TaxonomySubcategoryDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_vpn taxonomy subcategory model."""

    taxonomy_category_id: uuid.UUID | None = None
    code: str | None = None
    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None

    category: "TaxonomyCategoryDE" | None = None  # type: ignore
