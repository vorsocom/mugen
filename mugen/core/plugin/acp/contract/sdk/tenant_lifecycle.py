"""Tenant lifecycle extension contracts for ACP plugins."""

from __future__ import annotations

__all__ = [
    "AcpTenantLifecycleContributor",
    "register_tenant_lifecycle_contributor",
    "tenant_lifecycle_contributors",
]

from typing import Protocol

from mugen.core.plugin.acp.contract.sdk.registry import IAdminRegistry
from mugen.core.plugin.acp.domain.tenant import TenantDE


class AcpTenantLifecycleContributor(Protocol):
    """Plugin extension point for ACP tenant lifecycle events."""

    async def tenant_created(
        self,
        *,
        tenant: TenantDE,
        registry: IAdminRegistry,
    ) -> None:
        """React after an ACP tenant has been created."""


_TENANT_LIFECYCLE_CONTRIBUTORS: list[AcpTenantLifecycleContributor] = []


def register_tenant_lifecycle_contributor(
    contributor: AcpTenantLifecycleContributor,
) -> None:
    """Register a tenant lifecycle contributor once by object identity."""
    if any(registered is contributor for registered in _TENANT_LIFECYCLE_CONTRIBUTORS):
        return
    _TENANT_LIFECYCLE_CONTRIBUTORS.append(contributor)


def tenant_lifecycle_contributors() -> tuple[AcpTenantLifecycleContributor, ...]:
    """Return registered tenant lifecycle contributors in registration order."""
    return tuple(_TENANT_LIFECYCLE_CONTRIBUTORS)
