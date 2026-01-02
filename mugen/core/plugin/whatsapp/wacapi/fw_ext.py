"""Provides an implementation of IFWExtension for the wacapi plugin."""

__all__ = ["WACAPIFWExtension"]

from types import SimpleNamespace

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway


class WACAPIFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """An implementation of IFWFramework for the wacapi plugin."""

    def __init__(
        self,
        config_provider=lambda: di.container.config,
        rsg_provider=lambda: di.container.relational_storage_gateway,
    ) -> None:
        self._config: SimpleNamespace = config_provider()
        self._rsg: IRelationalStorageGateway = rsg_provider()

    @property
    def platforms(self) -> list[str]:
        return ["whatsapp"]

    async def setup(self, app: Quart) -> None:

        # Import endpoints now that services are available.
        # pylint: disable=import-outside-toplevel
        # pylint: disable=unused-import
        import mugen.core.plugin.whatsapp.wacapi.api.webhook
