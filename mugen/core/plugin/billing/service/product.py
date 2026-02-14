"""Provides a CRUD service for billing products."""

__all__ = ["ProductService"]

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway

from mugen.core.plugin.billing.contract.service.product import IProductService
from mugen.core.plugin.billing.domain import ProductDE


class ProductService(  # pylint: disable=too-few-public-methods
    IRelationalService[ProductDE],
    IProductService,
):
    """A CRUD service for billing products."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ProductDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
