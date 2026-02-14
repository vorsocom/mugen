"""Provides a service contract for TaxonomyCategoryDE-related services."""

__all__ = ["ITaxonomyCategoryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import TaxonomyCategoryDE


class ITaxonomyCategoryService(
    ICrudService[TaxonomyCategoryDE],
    ABC,
):
    """A service contract for TaxonomyCategoryDE-related services."""
