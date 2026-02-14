"""Provides an implementation of IFWExtension for the ops_metering plugin."""

__all__ = ["OpsMeteringFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class OpsMeteringFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """OPS metering framework extension."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.ops_metering.api  # noqa: F401
