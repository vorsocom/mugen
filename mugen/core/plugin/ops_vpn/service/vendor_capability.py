"""Provides a CRUD service for vendor capabilities."""

__all__ = ["VendorCapabilityService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.vendor_capability import (
    IVendorCapabilityService,
)
from mugen.core.plugin.ops_vpn.domain import VendorCapabilityDE


class VendorCapabilityService(  # pylint: disable=too-few-public-methods
    IRelationalService[VendorCapabilityDE],
    IVendorCapabilityService,
):
    """A CRUD service for vendor capabilities."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorCapabilityDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
