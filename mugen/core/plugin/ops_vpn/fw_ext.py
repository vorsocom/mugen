"""Provides an implementation of IFWExtension for the ops_vpn plugin."""

__all__ = ["OpsVpnFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class OpsVpnFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """OPS VPN framework extension."""

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP's generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.ops_vpn.api  # noqa: F401
