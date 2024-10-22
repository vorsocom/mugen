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

        # We do not expect to get any exceptions here.
        try:
            with self.assertLogs(logger="test_app", level="ERROR") as logger:
                Config.init_app(app)

                # The Quart app logger level cannot be set because
                # LOG_LEVEL is not configured.
                self.assertEqual(
                    logger.output[0], "ERROR:test_app:LOG_LEVEL not configured."
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_log_level_configured(self) -> None:
        """Test effect of LOG_LEVEL being configured."""

        # Create dummy app.
        app = Quart("test_app")

        # Set LOG_LEVEL
        app.config["LOG_LEVEL"] = 10

        # We do not expect to get any exceptions here.
        try:
            with self.assertNoLogs():
                Config.init_app(app)
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")
