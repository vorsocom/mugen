"""Provides an implementation of IPlatformService."""

__all__ = ["DefaultPlatformService"]

from types import SimpleNamespace

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.service.platform import IPlatformService
from mugen.core.utility.platforms import normalize_platforms


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
        return normalize_platforms(
            getattr(getattr(self._config, "mugen", SimpleNamespace()), "platforms", [])
        )

    def extension_supported(self, ext) -> bool:
        ext_platforms = normalize_platforms(getattr(ext, "platforms", []))
        return not ext_platforms or bool(set(ext_platforms) & set(self.active_platforms))
