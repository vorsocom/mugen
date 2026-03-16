"""Public exports for web media storage gateways."""

__all__ = [
    "DefaultMediaStorageGateway",
    "ObjectMediaStorageGateway",
]

from mugen.core.gateway.storage.media.provider import DefaultMediaStorageGateway
from mugen.core.gateway.storage.media.object import ObjectMediaStorageGateway
