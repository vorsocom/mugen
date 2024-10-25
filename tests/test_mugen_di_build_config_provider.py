"""Provides unit tests for mugen.core.di._build_config_provider."""

import unittest

from mugen.core import di


# pylint: disable=protected-access
class TestDIBuildConfigProvider(unittest.TestCase):
    """Unit tests for mugen.core.di._build_config_provider."""

    def test_null_parameters(self) -> None:
        """Test effects when null parameters are passed."""
        # Expect a SystemExit to be raised
        # due to null injector.
        with self.assertRaises(SystemExit):
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
