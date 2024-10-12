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

    async def test_config_variable_not_set(self) -> None:
        """Test endpoint called when platform configuration is unavailable."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(),
        }

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @unittest.mock.patch(target="quart.current_app.logger")
            @whatsapp_platform_required
            async def endpoint(*args, **kwargs):
                pass

            # We supposed to get an exception because the required platform
            # configuration is not available.
            with self.assertRaises(werkzeug.exceptions.InternalServerError):
                # Try calling endpoint.
                await endpoint()

    async def test_whatsapp_platform_is_enabled(self) -> None:
        """Test endpoint called when WhatsApp is enabled."""
        # Create dummy app to get context.
        app = Quart("test")

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix", "whatsapp"],
                ),
            ),
        }

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @unittest.mock.patch(target="quart.current_app.logger")
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

        # Create dummy config object to patch current_app.config.
        app.config = app.config | {
            "DEBUG": True,
            "ENV": SimpleNamespace(
                mugen=SimpleNamespace(
                    platforms=lambda: ["matrix", "telnet"],
                ),
            ),
        }

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @unittest.mock.patch(target="quart.current_app.logger")
            @whatsapp_platform_required
            async def endpoint(*args, **kwargs):
                pass

            # We must get an exception since the WhatsApp platform is
            # not enabled.
            with self.assertRaises(werkzeug.exceptions.NotImplemented):
                await endpoint()
