"""Provides a service contract for LedgerEntryDE-related services."""

__all__ = ["ILedgerEntryService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import LedgerEntryDE


class ILedgerEntryService(
    ICrudService[LedgerEntryDE],
    ABC,
):
    """A service contract for LedgerEntryDE-related services."""
