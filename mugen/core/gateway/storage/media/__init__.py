"""Public exports for web media storage gateways."""

__all__ = [
    "FilesystemMediaStorageGateway",
    "ObjectMediaStorageGateway",
]

from mugen.core.gateway.storage.media.filesystem import FilesystemMediaStorageGateway
from mugen.core.gateway.storage.media.object import ObjectMediaStorageGateway
