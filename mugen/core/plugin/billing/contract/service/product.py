"""Provides a service contract for ProductDE-related services."""

__all__ = ["IProductService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import ProductDE


class IProductService(
    ICrudService[ProductDE],
    ABC,
):
    """A service contract for ProductDE-related services."""
