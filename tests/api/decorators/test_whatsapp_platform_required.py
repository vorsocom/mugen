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
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace()

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @whatsapp_platform_required(config=config)  # replace config
            async def endpoint(*_args, **_kwargs):
                pass

            # We're supposed to get an exception because the required platform
            # configuration is not available.
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.InternalServerError),
            ):
                # Try calling endpoint.
                await endpoint()

    async def test_whatsapp_platform_not_enabled(self) -> None:
        """Test NotImplmented raised when WhatsApp not enabled."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["matrix", "telnet"],
            ),
        )

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @whatsapp_platform_required(config=config)  # replace config
            async def endpoint(*_args, **_kwargs):
                pass

            # We must get an exception since the Matrix platform is
            # not enabled.
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.NotImplemented),
            ):
                await endpoint()

    async def test_whatsapp_platform_is_enabled(self) -> None:
        """Test endpoint called when WhatsApp is enabled."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["matrix", "whatsapp"],
            ),
        )

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @whatsapp_platform_required(config=config)  # replace config
            async def endpoint(*_args, **_kwargs):
                pass

            with self.assertNoLogs():
                # Try calling endpoint.
                await endpoint()
