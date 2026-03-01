"""Public exports for web media storage gateways."""

__all__ = [
    "DefaultMediaStorageGateway",
    "FilesystemMediaStorageGateway",
    "ObjectMediaStorageGateway",
]

from mugen.core.gateway.storage.media.provider import DefaultMediaStorageGateway
from mugen.core.gateway.storage.media.filesystem import FilesystemMediaStorageGateway
from mugen.core.gateway.storage.media.object import ObjectMediaStorageGateway
