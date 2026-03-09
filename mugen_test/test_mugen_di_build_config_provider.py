"""Provides unit tests for mugen.core.di._build_config_provider."""

import unittest

from mugen.core import di


# pylint: disable=protected-access
class TestDIBuildConfigProvider(unittest.TestCase):
    """Unit tests for mugen.core.di._build_config_provider."""

    def test_null_parameters(self) -> None:
        """Test effects when null parameters are passed."""
        # Expect runtime validation failure for invalid payload.
        with self.assertRaises(RuntimeError):
            config = None
            injector = None
            di._build_config_provider(config, injector)

    def test_no_exception(self) -> None:
        """Test normal execution."""
        try:
            config = {}
            injector = di.injector.DependencyInjector()
            di._build_config_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here if the injector
            # is correctly typed.
            self.fail("Exception raised unexpectedly ")

    def test_invalid_injector_raises_runtime_error(self) -> None:
        with self.assertRaises(RuntimeError):
            di._build_config_provider({}, injector=object())

    def test_bootstrap_logger_falls_back_to_root_when_config_not_dict(self) -> None:
        logger = di._get_bootstrap_provider_logger(config=[])
        self.assertEqual(logger.name, "root")

    def test_bootstrap_logger_uses_configured_name(self) -> None:
        logger = di._get_bootstrap_provider_logger(
            config={"mugen": {"logger": {"name": "bootstrap.test"}}}
        )
        self.assertEqual(logger.name, "bootstrap.test")
