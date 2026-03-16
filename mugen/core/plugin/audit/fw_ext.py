"""Provides an implementation of IFWExtension for the audit plugin."""

__all__ = ["AuditFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class AuditFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """Framework extension for the audit plugin."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (none currently).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.audit.api  # noqa: F401
