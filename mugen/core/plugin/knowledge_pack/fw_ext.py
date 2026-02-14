"""Provides an implementation of IFWExtension for the knowledge_pack plugin."""

__all__ = ["KnowledgePackFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class KnowledgePackFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Knowledge Pack framework extension."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.knowledge_pack.api  # noqa: F401
