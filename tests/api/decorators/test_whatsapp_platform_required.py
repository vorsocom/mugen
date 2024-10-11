"""Provides unit tests for whatsapp_platform_required API decorator."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.decorators import whatsapp_platform_required


class TestWhatsAppPlatformRequired(unittest.IsolatedAsyncioTestCase):
    """Unit tests for whatsapp_platform_required API decorator."""

    async def test_whatsapp_platform_is_enabled(self) -> None:
        """Test endpoint called when WhatsApp is enabled."""
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
            @whatsapp_platform_required
            async def endpoint(*args, **kwargs):
                pass

            try:
                # Try calling endpoint.
                await endpoint()
            except werkzeug.exceptions.NotImplemented:
                # We are not supposed to get an exception since the WhatsApp
                # platform is enabled.
                self.fail("NotImplemented exception raised uexpectedly.")

    async def test_whatsapp_platform_not_enabled(self) -> None:
        """Test NotImplmented raised when WhatsApp not enabled."""
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
            @whatsapp_platform_required
            async def endpoint(*args, **kwargs):
                pass

            # We must get an exception since the WhatsApp platform is
            # not enabled.
            with self.assertRaises(werkzeug.exceptions.NotImplemented):
                await endpoint()
