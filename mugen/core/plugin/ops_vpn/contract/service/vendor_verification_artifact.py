"""Provides a service contract for VendorVerificationArtifactDE-related services."""

__all__ = ["IVendorVerificationArtifactService"]

from abc import ABC

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.ops_vpn.domain import VendorVerificationArtifactDE


class IVendorVerificationArtifactService(
    ICrudService[VendorVerificationArtifactDE],
    ABC,
):
    """A service contract for VendorVerificationArtifactDE-related services."""
