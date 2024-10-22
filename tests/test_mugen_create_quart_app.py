"""Provides unit tests for the mugen init script."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

from mugen import create_quart_app


class TestMuGenInitCreateQuartApp(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the muGen init script."""

    async def test_mugen_toml_not_available(self):
        """Test output when mugen.toml is not available."""

        # Create dummy configuration for testing.
        dummy_config = SimpleNamespace()

        with self.assertRaises(SystemExit):
            create_quart_app(config=dummy_config)

    async def test_mugen_toml_invalid_config_name(self):
        """Test output when mugen.toml is not available."""

        # Create dummy configuration for testing.
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="dev",
            ),
        )

        with self.assertRaises(SystemExit):
            create_quart_app(dummy_config)

    async def test_default_environment(self):
        """Test output for default environment."""

        # Create dummy configuration for testing.
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="default",
            ),
        )

        app = create_quart_app(dummy_config)
        self.assertIsInstance(app, Quart)
        self.assertEqual(app.config["DEBUG"], True)
        self.assertEqual(app.config["LOG_LEVEL"], 10)

    async def test_development_environment(self):
        """Test output for development environment."""

        # Create dummy configuration for testing.
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="development",
            ),
        )

        app = create_quart_app(dummy_config)
        self.assertIsInstance(app, Quart)
        self.assertEqual(app.config["DEBUG"], True)
        self.assertEqual(app.config["LOG_LEVEL"], 10)

    async def test_testing_environment(self):
        """Test output for testing environment."""

        # Create dummy configuration for testing.
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="testing",
            ),
        )

        app = create_quart_app(dummy_config)
        self.assertIsInstance(app, Quart)
        self.assertEqual(app.config["DEBUG"], True)
        self.assertEqual(app.config["TESTING"], True)
        self.assertEqual(app.config["LOG_LEVEL"], 20)

    async def test_production_environment(self):
        """Test output for production environment."""

        # Create dummy configuration for testing.
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="production",
            ),
        )

        app = create_quart_app(dummy_config)
        self.assertIsInstance(app, Quart)
        self.assertEqual(app.config["DEBUG"], False)
        self.assertEqual(app.config["LOG_LEVEL"], 30)
