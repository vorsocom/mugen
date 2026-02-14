"""Provides a service contract for VendorVerificationDE-related services."""

__all__ = ["IVendorVerificationService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VendorVerificationDE


class IVendorVerificationService(
    ICrudService[VendorVerificationDE],
    ABC,
):
    """A service contract for VendorVerificationDE-related services."""
