"""Provides an implementation of IFWExtension for the billing plugin."""

__all__ = ["BillingFWExtension"]

from quart import Quart

from mugen.core.contract.extension.fw import IFWExtension


class BillingFWExtension(IFWExtension):  # pylint: disable=too-few-public-methods
    """
    Billing framework extension.

    The billing plugin relies on ACP for:
    - Admin registry initialization and runtime binding (AdminFWExtension)
    - Generic CRUD/action API endpoints exposed under core/acp/v1

    Therefore, this FW extension is intentionally lightweight and only imports
    any billing-specific endpoints (if/when added).
    """

    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app: Quart) -> None:  # noqa: ARG002
        # Import endpoints (currently none beyond ACP's generic surface).
        # pylint: disable=import-outside-toplevel, unused-import
        import mugen.core.plugin.billing.api  # noqa: F401
