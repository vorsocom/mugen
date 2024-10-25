"""Provides unit tests for mugen.core.di"""

from textwrap import dedent
import unittest
import unittest.mock

from mugen.core import di


# pylint: disable=protected-access
class TestDILoadConfig(unittest.TestCase):
    """Unit tests for mugen.core.di"""

    def test_config_file_not_found(self) -> None:
        """Test effects of unavailable config file."""

        # Expect SystemExit since the config file would
        # not be found.
        with self.assertRaises(SystemExit):
            di._load_config("unavailable_file.toml")

    def test_config_file_is_available(self) -> None:
        """Test effects of available config file."""

        # Create dummy toml content.
        env = "testing"
        toml_content = f"""\
        [mugen]
        environment = "{env}"
        """

        # Create dummy file to patch builtins.open.
        toml_file = unittest.mock.mock_open(read_data=dedent(toml_content))

        # Patch builtins.open in this context.
        with unittest.mock.patch(target="builtins.open", new=toml_file):
            try:
                config = di._load_config("")
                self.assertIsInstance(config, dict)
                self.assertEqual(config["mugen"]["environment"], env)
            except:  # pylint: disable=bare-except
                # If we get here the test has failed since
                # the configuration should've been loaded
                # successfully and no exceptions should've
                # been raised.
                self.fail("Exception raised unexpectedly.")
