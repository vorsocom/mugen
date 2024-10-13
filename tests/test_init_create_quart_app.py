"""Provides unit tests for the mugen init script."""

import unittest
import unittest.mock

from quart import Quart

from mugen import create_quart_app


class TestMuGenInitCreateQuartApp(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the muGen init script."""

    async def test_mugen_toml_not_available(self):
        """Test output when mugen.toml is not available."""

        with unittest.mock.patch(target="mugen.mugen.logger"), self.assertRaises(
            SystemExit
        ):
            create_quart_app("")

    async def test_mugen_toml_invalid_config_name(self):
        """Test output when mugen.toml is not available."""

        # Dummy file
        dummy_config = unittest.mock.mock_open(
            read_data="""
[mugen]
environment = "dev"
""",
        )

        with unittest.mock.patch(target="mugen.mugen.logger"), unittest.mock.patch(
            target="builtins.open", new=dummy_config
        ), self.assertRaises(SystemExit):
            create_quart_app("")

    async def test_default_environment(self):
        """Test output for default environment."""

        # Dummy file
        dummy_config = unittest.mock.mock_open(
            read_data="""
[mugen]
environment = "default"
""",
        )

        with unittest.mock.patch(target="mugen.mugen.logger"), unittest.mock.patch(
            target="mugen.di.logging_gateway"
        ), unittest.mock.patch(target="builtins.open", new=dummy_config):
            app = create_quart_app("")
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], True)
            self.assertEqual(app.config["LOG_LEVEL"], 10)

    async def test_development_environment(self):
        """Test output for development environment."""

        # Dummy file
        dummy_config = unittest.mock.mock_open(
            read_data="""
[mugen]
environment = "development"
""",
        )

        with unittest.mock.patch(target="mugen.mugen.logger"), unittest.mock.patch(
            target="mugen.di.logging_gateway"
        ), unittest.mock.patch(target="builtins.open", new=dummy_config):
            app = create_quart_app("")
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], True)
            self.assertEqual(app.config["LOG_LEVEL"], 10)

    async def test_testing_environment(self):
        """Test output for testing environment."""

        # Dummy file
        dummy_config = unittest.mock.mock_open(
            read_data="""
[mugen]
environment = "testing"
""",
        )

        with unittest.mock.patch(target="mugen.mugen.logger"), unittest.mock.patch(
            target="mugen.di.logging_gateway"
        ), unittest.mock.patch(target="builtins.open", new=dummy_config):
            app = create_quart_app("")
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], True)
            self.assertEqual(app.config["TESTING"], True)
            self.assertEqual(app.config["LOG_LEVEL"], 20)

    async def test_production_environment(self):
        """Test output for production environment."""

        # Dummy file
        dummy_config = unittest.mock.mock_open(
            read_data="""
[mugen]
environment = "production"
""",
        )

        with unittest.mock.patch(target="mugen.mugen.logger"), unittest.mock.patch(
            target="mugen.di.logging_gateway"
        ), unittest.mock.patch(target="builtins.open", new=dummy_config):
            app = create_quart_app("")
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], False)
            self.assertEqual(app.config["LOG_LEVEL"], 30)
