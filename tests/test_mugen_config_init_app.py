"""Provides unit tests for mugen.config.Config.init_app."""

import unittest
import unittest.mock

from quart import Quart

from mugen.config import Config


class TestMuGenConfigInitApp(unittest.TestCase):
    """Unit tests for mugen.config.Config.init_app."""

    def test_log_level_not_configured(self) -> None:
        """Test effect of missing LOG_LEVEL configuration."""

        # Create dummy app.
        app = Quart("test_app")

        # Suppress logger output.
        app.logger.error = unittest.mock.Mock()

        # We do not expect to get any exceptions here.
        try:
            Config.init_app(app)

            # app.logger.error should have been called.
            self.assertTrue(app.logger.error.called)
        except:
            self.fail("Exception raised unexpectedly.")

    def test_log_level_configured(self) -> None:
        """Test effect of LOG_LEVEL being configured."""

        # Create dummy app.
        app = Quart("test_app")

        # Set LOG_LEVEL
        app.config["LOG_LEVEL"] = 10

        # Suppress logger output.
        app.logger.error = unittest.mock.Mock()

        # We do not expect to get any exceptions here.
        try:
            Config.init_app(app)

            # app.logger.error should NOT have been called.
            self.assertFalse(app.logger.error.called)
        except:
            self.fail("Exception raised unexpectedly.")
