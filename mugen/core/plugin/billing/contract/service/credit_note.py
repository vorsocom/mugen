"""Provides a service contract for CreditNoteDE-related services."""

__all__ = ["ICreditNoteService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import CreditNoteDE


class ICreditNoteService(
    ICrudService[CreditNoteDE],
    ABC,
):
    """A service contract for CreditNoteDE-related services."""
