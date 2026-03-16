"""Provides a CRUD service for billing credit notes."""

__all__ = ["CreditNoteService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.billing.contract.service.credit_note import ICreditNoteService
from mugen.core.plugin.billing.domain import CreditNoteDE


class CreditNoteService(  # pylint: disable=too-few-public-methods
    IRelationalService[CreditNoteDE],
    ICreditNoteService,
):
    """A CRUD service for billing credit notes."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=CreditNoteDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
