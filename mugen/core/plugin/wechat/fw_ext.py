"""Provides an implementation of IFWExtension for WeChat support."""

__all__ = ["WeChatFWExtension"]

from types import SimpleNamespace

from quart import Quart

from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.contract.gateway.storage.rdbms import IRelationalStorageGateway


def _config_provider():
    return di.container.config


def _rsg_provider():
    return di.container.relational_storage_gateway


class WeChatFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """An implementation of IFWExtension for WeChat support."""

    def __init__(
        self,
        config_provider=_config_provider,
        rsg_provider=_rsg_provider,
    ) -> None:
        self._config: SimpleNamespace = config_provider()
        self._rsg: IRelationalStorageGateway = rsg_provider()

    @property
    def platforms(self) -> list[str]:
        return ["wechat"]

    async def setup(self, app: Quart) -> None:
        _ = app
        _ = self._config
        _ = self._rsg

        # Import endpoints now that services are available.
        # pylint: disable=import-outside-toplevel
        # pylint: disable=unused-import
        import mugen.core.plugin.wechat.api.webhook
