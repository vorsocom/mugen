"""Provides a CRUD service for vendor verification artifacts."""

__all__ = ["VendorVerificationArtifactService"]

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_vpn.contract.service.vendor_verification_artifact import (
    IVendorVerificationArtifactService,
)
from mugen.core.plugin.ops_vpn.domain import VendorVerificationArtifactDE


class VendorVerificationArtifactService(  # pylint: disable=too-few-public-methods
    IRelationalService[VendorVerificationArtifactDE],
    IVendorVerificationArtifactService,
):
    """A CRUD service for vendor verification artifacts."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=VendorVerificationArtifactDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
