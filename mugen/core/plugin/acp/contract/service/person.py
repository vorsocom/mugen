"""Provides a service contract for Person-related services."""

__all__ = ["IPersonService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.domain import PersonDE


class IPersonService(
    ICrudService[PersonDE],
    ABC,
):
    """A service contract for Person-related services."""
