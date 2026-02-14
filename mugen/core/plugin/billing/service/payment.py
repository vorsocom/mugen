"""Provides a CRUD service for billing payments."""

__all__ = ["PaymentService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.payment import IPaymentService
from mugen.core.plugin.billing.domain import PaymentDE


class PaymentService(  # pylint: disable=too-few-public-methods
    IRelationalService[PaymentDE],
    IPaymentService,
):
    """A CRUD service for billing payments."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PaymentDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
