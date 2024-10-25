"""Provides unit tests for matrix_platform_required API decorator."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart
import werkzeug
import werkzeug.exceptions

from util.decorator import matrix_platform_required


class TestMatrixPlatformRequired(unittest.IsolatedAsyncioTestCase):
    """Unit tests for matrix_platform_required API decorator."""

    async def test_config_variable_not_set(self) -> None:
        """Test endpoint called when platform configuration is unavailable."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace()

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @matrix_platform_required(config=config)  # replace config
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

    async def test_matrix_platform_not_enabled(self) -> None:
        """Test NotImplmented raised when Matrix not enabled."""
        # Create dummy app to get context.
        app = Quart("test_app")

        # Create dummy config for testing.
        config = SimpleNamespace(
            mugen=SimpleNamespace(
                platforms=["whatsapp"],
            ),
        )

        # Use dummy context.
        async with app.app_context():

            # Define and patch dummy endpoint.
            @matrix_platform_required(config=config)  # replace config
            async def endpoint(*_args, **_kwargs):
                pass

            # We must get an exception since the Matrix platform is
            # not enabled.
            with (
                self.assertLogs(logger="test_app", level="ERROR"),
                self.assertRaises(werkzeug.exceptions.NotImplemented),
            ):
                await endpoint()

    async def test_matrix_platform_is_enabled(self) -> None:
        """Test endpoint called when Matrix is enabled."""
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
            @matrix_platform_required(config=config)  # replace config
            async def endpoint(*_args, **_kwargs):
                pass

            with self.assertNoLogs():
                # Try calling endpoint.
                await endpoint()
