"""Provides a service contract for VendorCapabilityDE-related services."""

__all__ = ["IVendorCapabilityService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VendorCapabilityDE


class IVendorCapabilityService(
    ICrudService[VendorCapabilityDE],
    ABC,
):
    """A service contract for VendorCapabilityDE-related services."""
