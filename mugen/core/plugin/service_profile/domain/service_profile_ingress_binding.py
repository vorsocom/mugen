"""Provides a domain entity for Service Profile ingress assignments."""

from __future__ import annotations

__all__ = ["ServiceProfileIngressBindingDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ServiceProfileIngressBindingDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for an exact Service Profile ingress assignment."""

    service_profile_id: uuid.UUID | None = None
    ingress_binding_id: uuid.UUID | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None
