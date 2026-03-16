"""Provides a CRUD service for vendor performance events."""

__all__ = ["VendorPerformanceEventService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.vendor_performance_event import (
    IVendorPerformanceEventService,
)
from mugen.core.plugin.ops_vpn.domain import VendorPerformanceEventDE


class VendorPerformanceEventService(  # pylint: disable=too-few-public-methods
    IRelationalService[VendorPerformanceEventDE],
    IVendorPerformanceEventService,
):
    """A CRUD service for vendor performance events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorPerformanceEventDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
