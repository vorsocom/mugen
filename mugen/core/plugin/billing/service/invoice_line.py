"""Provides a CRUD service for billing invoice lines."""

__all__ = ["InvoiceLineService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.invoice_line import IInvoiceLineService
from mugen.core.plugin.billing.domain import InvoiceLineDE


class InvoiceLineService(  # pylint: disable=too-few-public-methods
    IRelationalService[InvoiceLineDE],
    IInvoiceLineService,
):
    """A CRUD service for billing invoice lines."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=InvoiceLineDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
