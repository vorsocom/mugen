"""Provides an implementation of IFWExtension for the ops_connector plugin."""

__all__ = ["OpsConnectorFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class OpsConnectorFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """OPS connector framework extension."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.ops_connector.api  # noqa: F401
