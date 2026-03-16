"""Provides an implementation of IFWExtension for the ops_governance plugin."""

__all__ = ["OpsGovernanceFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class OpsGovernanceFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Framework extension for the ops_governance plugin."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (none currently).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.ops_governance.api  # noqa: F401
