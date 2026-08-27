"""Provides a CRUD service for billing invoice lines."""

__all__ = ["InvoiceLineService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.invoice_line import IInvoiceLineService
from mugen.core.plugin.billing.domain import InvoiceLineDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class InvoiceLineService(  # pylint: disable=too-few-public-methods
    BillingReferenceService[InvoiceLineDE],
    IInvoiceLineService,
):
    """A CRUD service for billing invoice lines."""

    _active_reference_tables = {
        "tax_code_id": ("billing_tax_code", "TaxCodeId"),
        "tax_rate_id": ("billing_tax_rate", "TaxRateId"),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=InvoiceLineDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
