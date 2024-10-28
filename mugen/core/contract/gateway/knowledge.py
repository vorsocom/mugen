"""Provides an abstract base class for knowledge gateways."""

__all__ = ["IKnowledgeGateway"]

from abc import ABC, abstractmethod

from mugen.core.contract.dto.vendorparams import VendorParams


class IKnowledgeGateway(ABC):  # pylint: disable=too-few-public-methods
    """An ABC for knowledge retrival gateways."""

    @abstractmethod
    async def search(self, params: VendorParams) -> list:
        """Perform knwoledge lookup."""
