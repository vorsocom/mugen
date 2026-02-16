"""Provides an implementation of IFWExtension for the web plugin."""

__all__ = ["WebFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class WebFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Framework extension for web platform API routes."""

    @property
    def platforms(self) -> list[str]:
        return ["web"]

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import routes at setup time so DI services are fully available.
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.web.api.chat  # noqa: F401
