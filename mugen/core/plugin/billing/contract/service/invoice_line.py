"""Provides a service contract for InvoiceLineDE-related services."""

__all__ = ["IInvoiceLineService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.billing.domain import InvoiceLineDE


class IInvoiceLineService(
    ICrudService[InvoiceLineDE],
    ABC,
):
    """A service contract for InvoiceLineDE-related services."""
