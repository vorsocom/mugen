"""Provides unit tests for matrix_platform_required API decorator."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from mugen.core.api.decorators import matrix_platform_required


class TestMatrixPlatformRequired(unittest.IsolatedAsyncioTestCase):
    """Unit tests for matrix_platform_required API decorator."""

    async def test_config_variable_not_set(self) -> None:
        """Test endpoint called when platform configuration is unavailable."""
        # Create dummy app to get context.
        app = Quart("test")

        # Use dummy context.
        async with app.app_context():

            # Create dummy config object to patch current_app.config.
            config = lambda: {
                "ENV": SimpleNamespace(),
                "DEBUG": True,
            }

            # Define and patch dummy endpoint.
            @unittest.mock.patch(
                target="quart.current_app.config",
                new_callable=config,
            )
            @unittest.mock.patch(target="quart.current_app.logger")
            @matrix_platform_required
            async def endpoint(*args, **kwargs):
                pass

            # We supposed to get an exception because the required platform
            # configuration is not available.
            with self.assertRaises(werkzeug.exceptions.InternalServerError):
                # Try calling endpoint.
                await endpoint()

    async def test_matrix_platform_is_enabled(self) -> None:
        """Test endpoint called when Matrix is enabled."""
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
            @matrix_platform_required
            async def endpoint(*args, **kwargs):
                pass

            try:
                # Try calling endpoint.
                await endpoint()
            except werkzeug.exceptions.NotImplemented:
                # We are not supposed to get an exception since the Matrix
                # platform is enabled.
                self.fail("NotImplemented exception raised uexpectedly.")

    async def test_matrix_platform_not_enabled(self) -> None:
        """Test NotImplmented raised when Matrix not enabled."""
        # Create dummy app to get context.
        app = Quart("test")

        # Use dummy context.
        async with app.app_context():

            # Create dummy config object to patch current_app.config.
            config = lambda: {
                "ENV": SimpleNamespace(
                    mugen=SimpleNamespace(
                        platforms=lambda: ["whatsapp"],
                    ),
                ),
            }

            # Define and patch dummy endpoint.
            @unittest.mock.patch(
                target="quart.current_app.config",
                new_callable=config,
            )
            @matrix_platform_required
            async def endpoint(*args, **kwargs):
                pass

            # We must get an exception since the Matrix platform is
            # not enabled.
            with self.assertRaises(werkzeug.exceptions.NotImplemented):
                await endpoint()
