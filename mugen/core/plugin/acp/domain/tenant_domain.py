"""Provides a domain entity for the TenantDomain DB model."""

__all__ = ["TenantDomainDE"]

from dataclasses import dataclass
from datetime import datetime

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class TenantDomainDE(
    BaseDE, TenantScopedDEMixin
):  # pylint: disable=too-many-instance-attributes
    """A domain entity for the TenantDomain DB model."""

    domain: str | None = None

    verified_at: datetime | None = None

    is_primary: bool | None = None
