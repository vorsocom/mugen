"""Provides a service contract for AccountDE-related services."""

__all__ = ["IAccountService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import AccountDE


class IAccountService(
    ICrudService[AccountDE],
    ABC,
):
    """A service contract for AccountDE-related services."""
