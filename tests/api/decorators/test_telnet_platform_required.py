"""Provides unit tests for telnet_platform_required API decorator."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.decorators import telnet_platform_required


class TestTelnetPlatformRequired(unittest.IsolatedAsyncioTestCase):
    """Unit tests for telnet_platform_required API decorator."""

    async def test_telnet_platform_is_enabled(self) -> None:
        """Test endpoint called when Telnet is enabled."""
        # Create dummy app to get context.
        app = Quart("test")

        # Use dummy context.
        async with app.app_context():

            # Create dummy config object to patch current_app.config.
            config = lambda: {
                "ENV": SimpleNamespace(
                    mugen=SimpleNamespace(
                        platforms=lambda: ["matrix", "telnet"],
                    ),
                ),
            }

            # Define and patch dummy endpoint.
            @unittest.mock.patch(
                target="quart.current_app.config",
                new_callable=config,
            )
            @telnet_platform_required
            async def endpoint(*args, **kwargs):
                pass

            try:
                # Try calling endpoint.
                await endpoint()
            except werkzeug.exceptions.NotImplemented:
                # We are not supposed to get an exception since the Telnet
                # platform is enabled.
                self.fail("NotImplemented exception raised uexpectedly.")

    async def test_telnet_platform_not_enabled(self) -> None:
        """Test NotImplmented raised when Telnet not enabled."""
        # Create dummy app to get context.
        app = Quart("test")

        # Use dummy context.
        async with app.app_context():

            # Create dummy config object to patch current_app.config.
            config = lambda: {
                "ENV": SimpleNamespace(
                    mugen=SimpleNamespace(
                        platforms=lambda: ["matrix", "whatsapp"],
                    ),
                ),
            }

            # Define and patch dummy endpoint.
            @unittest.mock.patch(
                target="quart.current_app.config",
                new_callable=config,
            )
            @telnet_platform_required
            async def endpoint(*args, **kwargs):
                pass

            # We must get an exception since the Telnet platform is
            # not enabled.
            with self.assertRaises(werkzeug.exceptions.NotImplemented):
                await endpoint()
