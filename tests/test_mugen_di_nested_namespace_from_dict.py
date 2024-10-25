"""Provides unit tests for mugen.core.di._nested_namespace_from_dict."""

from types import SimpleNamespace
import unittest

from mugen.core import di


# pylint: disable=protected-access
class TestDINestedNamespaceFromDict(unittest.TestCase):
    """Unit tests for mugen.core.di._nested_namespace_from_dict."""

    def test_null_parameters(self):
        """Test effects of passing null parameters to function."""

        # Attempt to call the function with null parameters.
        try:
            di._nested_namespace_from_dict(items=None, ns=None)
        except:  # pylint: disable=bare-except
            # We should not get here because the function
            # should handle the AttributeError that would
            # result from calling items.keys().
            self.fail("Exception raised unexpectedly (null parameters).")

    def test_empty_dict(self):
        """Test effects of passing an empty dict to function."""

        # Attempt to call the function with an empty dict:
        try:
            di._nested_namespace_from_dict(items={}, ns=None)
        except:  # pylint: disable=bare-except
            # We should not get here because the function
            # should exit gracefully if an empty dict is passed.
            self.fail("Exception raised unexpectedly (empty dict).")

    def test_empty_list(self):
        """Test effects of passing a dict with an empty list to function."""

        # Create dict for testing.
        config = {"list": []}

        # Create empty namespace to be populated.
        namespace = SimpleNamespace()

        # Attempt to call the function with an empty list
        # somewhere in the dict:
        try:
            di._nested_namespace_from_dict(items=config, ns=namespace)
        except:  # pylint: disable=bare-except
            # We should not get here because the function
            # should handle the IndexError that would
            # result from calling items[key][0].
            self.fail("Exception raised unexpectedly (empty list).")

    def test_flat_dict(self):
        """Test output on passing flat dict."""

        # Create dict for testing.
        config = {
            "one": "1",
            "two": 2,
            "three": "| | |",
        }

        # Create empty namespace to be populated.
        namespace = SimpleNamespace()

        # Attempt to call the function with an empty dict:
        try:
            di._nested_namespace_from_dict(items=config, ns=namespace)
            self.assertTrue(hasattr(namespace, "three"))
            self.assertEqual(config["three"], namespace.three)
        except:  # pylint: disable=bare-except
            # We should not get here because the function
            # should exit gracefully if a valid dict is passed.
            self.fail("Exception raised unexpectedly (flat dict).")

    def test_nested_dict(self):
        """Test output on passing nested dict."""

        # Create dict for testing.
        config = {
            "nested_item": {
                "level1": True,
            },
            "flat_item": False,
        }

        # Create empty namespace to be populated.
        namespace = SimpleNamespace()

        # Attempt to call the function with an empty dict:
        try:
            di._nested_namespace_from_dict(items=config, ns=namespace)
            self.assertEqual(namespace.nested_item.level1, True)
            self.assertEqual(namespace.flat_item, False)
        except:  # pylint: disable=bare-except
            # We should not get here because the function
            # should exit gracefully if a valid dict is passed.
            self.fail("Exception raised unexpectedly (nested dict).")

    def test_list_of_dicts(self):
        """Test output on passing nested dict."""

        # Create dict for testing.
        config = {
            "nested_item": {
                "level1": True,
                "list": [
                    {
                        "first_item": "yes",
                    },
                    {
                        "second_item": [
                            {
                                "blah": "blah blah",
                            },
                            {
                                "lorem": "ipsum",
                            },
                            {
                                "test": "Bingo!",
                            },
                        ],
                    },
                ],
            }
        }

        # Create empty namespace to be populated.
        namespace = SimpleNamespace()

        # Attempt to call the function with an empty dict:
        try:
            di._nested_namespace_from_dict(items=config, ns=namespace)
            self.assertEqual(namespace.nested_item.list[0].first_item, "yes")
            self.assertEqual(
                namespace.nested_item.list[1].second_item[2].test,
                "Bingo!",
            )
        except:  # pylint: disable=bare-except
            # We should not get here because the function
            # should exit gracefully if a valid dict is passed.
            self.fail("Exception raised unexpectedly (list of dicts).")
