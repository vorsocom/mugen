"""Provides a service contract for VendorVerificationCheckDE-related services."""

__all__ = ["IVendorVerificationCheckService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VendorVerificationCheckDE


class IVendorVerificationCheckService(
    ICrudService[VendorVerificationCheckDE],
    ABC,
):
    """A service contract for VendorVerificationCheckDE-related services."""
