"""Provides an implementation of IFWExtension for the ops_workflow plugin."""

__all__ = ["OpsWorkflowFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class OpsWorkflowFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """OPS Workflow framework extension."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP's generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.ops_workflow.api  # noqa: F401
