"""Provides unit tests for the mugen init script."""

from types import SimpleNamespace
import unittest
import unittest.mock

from quart import Quart

from mugen import BootstrapConfigError, create_quart_app as _create_quart_app


def _logger_provider():
    return unittest.mock.Mock(
        debug=unittest.mock.Mock(),
        error=unittest.mock.Mock(),
    )


def create_quart_app(*args, **kwargs):
    """Wrapper to avoid depending on DI-backed logger provider in unit tests."""
    kwargs.setdefault("logger_provider", _logger_provider)
    return _create_quart_app(*args, **kwargs)


class TestMuGenInitCreateQuartApp(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the muGen init script."""

    async def test_mugen_toml_not_available(self):
        """Test output when mugen.toml is not available."""
        try:
            # Create dummy configuration for testing.
            dummy_config = SimpleNamespace()

            with self.assertRaises(BootstrapConfigError):
                create_quart_app(config_provider=lambda: dummy_config)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    async def test_mugen_toml_invalid_config_name(self):
        """Test output when mugen.toml is not available."""
        try:
            # Create dummy configuration for testing.
            dummy_config = SimpleNamespace(
                mugen=SimpleNamespace(
                    environment="dev",
                ),
            )

            with self.assertRaises(BootstrapConfigError):
                create_quart_app(config_provider=lambda: dummy_config)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    async def test_default_environment(self):
        """Test output for default environment."""
        try:
            # Create dummy configuration for testing.
            dummy_config = SimpleNamespace(
                mugen=SimpleNamespace(
                    environment="default",
                ),
                quart=SimpleNamespace(secret_key="0123456789abcdef0123456789abcdef"),
            )

            app = create_quart_app(config_provider=lambda: dummy_config)
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], True)
            self.assertEqual(app.config["LOG_LEVEL"], 10)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    async def test_development_environment(self):
        """Test output for development environment."""
        try:
            # Create dummy configuration for testing.
            dummy_config = SimpleNamespace(
                mugen=SimpleNamespace(
                    environment="development",
                ),
                quart=SimpleNamespace(secret_key="0123456789abcdef0123456789abcdef"),
            )

            app = create_quart_app(config_provider=lambda: dummy_config)
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], True)
            self.assertEqual(app.config["LOG_LEVEL"], 10)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    async def test_testing_environment(self):
        """Test output for testing environment."""
        try:
            # Create dummy configuration for testing.
            dummy_config = SimpleNamespace(
                mugen=SimpleNamespace(
                    environment="testing",
                ),
                quart=SimpleNamespace(secret_key="0123456789abcdef0123456789abcdef"),
            )

            app = create_quart_app(config_provider=lambda: dummy_config)
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], True)
            self.assertEqual(app.config["TESTING"], True)
            self.assertEqual(app.config["LOG_LEVEL"], 20)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    async def test_production_environment(self):
        """Test output for production environment."""
        try:
            # Create dummy configuration for testing.
            dummy_config = SimpleNamespace(
                mugen=SimpleNamespace(
                    environment="production",
                ),
                quart=SimpleNamespace(secret_key="0123456789abcdef0123456789abcdef"),
            )

            app = create_quart_app(config_provider=lambda: dummy_config)
            self.assertIsInstance(app, Quart)
            self.assertEqual(app.config["DEBUG"], False)
            self.assertEqual(app.config["LOG_LEVEL"], 30)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    async def test_rejects_weak_quart_secret_key(self):
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="development",
            ),
            quart=SimpleNamespace(secret_key="short-secret"),
        )

        with self.assertRaises(BootstrapConfigError):
            create_quart_app(config_provider=lambda: dummy_config)

    async def test_rejects_placeholder_quart_secret_key(self):
        dummy_config = SimpleNamespace(
            mugen=SimpleNamespace(
                environment="development",
            ),
            quart=SimpleNamespace(secret_key="<set-quart-secret-key>"),
        )

        with self.assertRaises(BootstrapConfigError):
            create_quart_app(config_provider=lambda: dummy_config)
