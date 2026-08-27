"""Provides a CRUD service for billing ledger entries."""

__all__ = ["LedgerEntryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.ledger_entry import ILedgerEntryService
from mugen.core.plugin.billing.domain import LedgerEntryDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class LedgerEntryService(  # pylint: disable=too-few-public-methods
    BillingReferenceService[LedgerEntryDE],
    ILedgerEntryService,
):
    """A CRUD service for billing ledger entries."""

    _currency_snapshot = True
    _active_reference_tables = {
        "currency_definition_id": (
            "billing_currency_definition",
            "CurrencyDefinitionId",
        ),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=LedgerEntryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
