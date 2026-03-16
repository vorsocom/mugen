"""Provides a service contract for CaseLinkDE-related services."""

__all__ = ["ICaseLinkService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_case.domain import CaseLinkDE


class ICaseLinkService(
    ICrudService[CaseLinkDE],
    ABC,
):
    """A service contract for CaseLinkDE-related services."""

