"""Provides an implementation of IPlatformService."""

__all__ = ["DefaultPlatformService"]

from types import SimpleNamespace

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.platform import IPlatformService


class DefaultPlatformService(IPlatformService):
    """An implementation of IPlatformService"""

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway

    @property
    def active_platforms(self) -> list[str]:
        return self._config.mugen.platforms

    def extension_supported(self, ext) -> bool:
        return (
            not ext.platforms
            or len(list(set(ext.platforms) & set(self.active_platforms))) != 0
        )
