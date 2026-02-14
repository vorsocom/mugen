"""Provides a domain entity for the CaseLink DB model."""

from __future__ import annotations

__all__ = ["CaseLinkDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.soft_delete import SoftDeleteDEMixin
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


# pylint: disable=too-many-instance-attributes
@dataclass
class CaseLinkDE(BaseDE, TenantScopedDEMixin, SoftDeleteDEMixin):
    """A domain entity for the ops_case CaseLink DB model."""

    case_id: uuid.UUID | None = None

    link_type: str | None = None
    target_namespace: str | None = None
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    target_ref: str | None = None
    target_display: str | None = None
    relationship_kind: str | None = None

    created_by_user_id: uuid.UUID | None = None
    attributes: dict[str, Any] | None = None

    case: "CaseDE" | None = None  # type: ignore

