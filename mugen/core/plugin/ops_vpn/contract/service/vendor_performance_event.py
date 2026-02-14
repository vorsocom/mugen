"""Provides a service contract for VendorPerformanceEventDE-related services."""

__all__ = ["IVendorPerformanceEventService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VendorPerformanceEventDE


class IVendorPerformanceEventService(
    ICrudService[VendorPerformanceEventDE],
    ABC,
):
    """A service contract for VendorPerformanceEventDE-related services."""
