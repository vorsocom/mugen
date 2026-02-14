"""Provides a service contract for TaxonomyDomainDE-related services."""

__all__ = ["ITaxonomyDomainService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import TaxonomyDomainDE


class ITaxonomyDomainService(
    ICrudService[TaxonomyDomainDE],
    ABC,
):
    """A service contract for TaxonomyDomainDE-related services."""
