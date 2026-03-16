"""Provides a CRUD service for billing ledger entries."""

__all__ = ["LedgerEntryService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.ledger_entry import ILedgerEntryService
from mugen.core.plugin.billing.domain import LedgerEntryDE


class LedgerEntryService(  # pylint: disable=too-few-public-methods
    IRelationalService[LedgerEntryDE],
    ILedgerEntryService,
):
    """A CRUD service for billing ledger entries."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=LedgerEntryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
