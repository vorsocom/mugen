"""Provides a CRUD service for vendor categories."""

__all__ = ["VendorCategoryService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.vendor_category import (
    IVendorCategoryService,
)
from mugen.core.plugin.ops_vpn.domain import VendorCategoryDE


class VendorCategoryService(  # pylint: disable=too-few-public-methods
    IRelationalService[VendorCategoryDE],
    IVendorCategoryService,
):
    """A CRUD service for vendor categories."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorCategoryDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
