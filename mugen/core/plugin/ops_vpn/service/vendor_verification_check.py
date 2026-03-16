"""Provides a CRUD service for vendor verification checks."""

__all__ = ["VendorVerificationCheckService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_vpn.contract.service.vendor_verification_check import (
    IVendorVerificationCheckService,
)
from mugen.core.plugin.ops_vpn.domain import VendorVerificationCheckDE


class VendorVerificationCheckService(  # pylint: disable=too-few-public-methods
    IRelationalService[VendorVerificationCheckDE],
    IVendorVerificationCheckService,
):
    """A CRUD service for vendor verification checks."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorVerificationCheckDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
