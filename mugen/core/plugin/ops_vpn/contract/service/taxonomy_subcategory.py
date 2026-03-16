"""Provides a service contract for TaxonomySubcategoryDE-related services."""

__all__ = ["ITaxonomySubcategoryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import TaxonomySubcategoryDE


class ITaxonomySubcategoryService(
    ICrudService[TaxonomySubcategoryDE],
    ABC,
):
    """A service contract for TaxonomySubcategoryDE-related services."""
