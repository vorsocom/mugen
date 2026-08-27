"""Provides a CRUD service for billing credit notes."""

__all__ = ["CreditNoteService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.plugin.billing.contract.service.credit_note import ICreditNoteService
from mugen.core.plugin.billing.domain import CreditNoteDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class CreditNoteService(  # pylint: disable=too-few-public-methods
    BillingReferenceService[CreditNoteDE],
    ICreditNoteService,
):
    """A CRUD service for billing credit notes."""

    _currency_snapshot = True
    _active_reference_tables = {
        "currency_definition_id": (
            "billing_currency_definition",
            "CurrencyDefinitionId",
        ),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=CreditNoteDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
