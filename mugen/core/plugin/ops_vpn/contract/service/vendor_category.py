"""Provides a service contract for VendorCategoryDE-related services."""

__all__ = ["IVendorCategoryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VendorCategoryDE


class IVendorCategoryService(
    ICrudService[VendorCategoryDE],
    ABC,
):
    """A service contract for VendorCategoryDE-related services."""
