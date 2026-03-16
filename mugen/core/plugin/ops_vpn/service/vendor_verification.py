"""Provides a CRUD service for vendor verification events."""

__all__ = ["VendorVerificationService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService

from mugen.core.plugin.ops_vpn.contract.service.vendor_verification import (
    IVendorVerificationService,
)
from mugen.core.plugin.ops_vpn.domain import VendorVerificationDE


class VendorVerificationService(  # pylint: disable=too-few-public-methods
    IRelationalService[VendorVerificationDE],
    IVendorVerificationService,
):
    """A CRUD service for vendor verification events."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorVerificationDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
