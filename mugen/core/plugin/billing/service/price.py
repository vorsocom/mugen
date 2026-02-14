"""Provides a CRUD service for billing prices."""

__all__ = ["PriceService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.price import IPriceService
from mugen.core.plugin.billing.domain import PriceDE


class PriceService(  # pylint: disable=too-few-public-methods
    IRelationalService[PriceDE],
    IPriceService,
):
    """A CRUD service for billing prices."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PriceDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
