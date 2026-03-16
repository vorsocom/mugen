"""Provides an implementation of IFWExtension for the channel_orchestration plugin."""

__all__ = ["ChannelOrchestrationFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class ChannelOrchestrationFWExtension(
    IFWExtension
):  # pylint: disable=too-few-public-methods
    """Framework extension for the channel_orchestration plugin."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.channel_orchestration.api  # noqa: F401
