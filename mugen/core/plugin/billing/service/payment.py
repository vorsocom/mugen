"""Provides a CRUD service for billing payments."""

__all__ = ["PaymentService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.payment import IPaymentService
from mugen.core.plugin.billing.domain import PaymentDE
from mugen.core.plugin.billing.service.reference import BillingReferenceService


class PaymentService(  # pylint: disable=too-few-public-methods
    BillingReferenceService[PaymentDE],
    IPaymentService,
):
    """A CRUD service for billing payments."""

    _currency_snapshot = True
    _active_reference_tables = {
        "currency_definition_id": (
            "billing_currency_definition",
            "CurrencyDefinitionId",
        ),
    }

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PaymentDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
