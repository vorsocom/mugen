"""Unit tests for provider spec integrity in mugen.core.di."""

import unittest

from mugen.core import di


# pylint: disable=protected-access
class TestDIProviderSpecIntegrity(unittest.TestCase):
    """Unit tests that guard declarative provider spec consistency."""

    def test_build_order_matches_non_logging_specs(self):
        """Build order should include every non-logging spec in declaration order."""
        expected = tuple(
            name for name in di._PROVIDER_SPECS if name != "logging_gateway"
        )
        self.assertEqual(di._PROVIDER_BUILD_ORDER, expected)

    def test_spec_keys_match_declared_provider_and_injector_names(self):
        """Spec key/provider_name/injector_attr should stay aligned."""
        for key, spec in di._PROVIDER_SPECS.items():
            self.assertEqual(key, spec.provider_name)
            self.assertEqual(spec.provider_name, spec.injector_attr)

    def test_constructor_bindings_reference_known_injector_attrs(self):
        """Each constructor binding should map to a known injector attribute."""
        injector = di.injector.DependencyInjector()
        known_attrs = {
            "config",
            *(s.injector_attr for s in di._PROVIDER_SPECS.values()),
        }

        for spec in di._PROVIDER_SPECS.values():
            for arg_name, injector_attr in spec.constructor_bindings:
                self.assertIsInstance(arg_name, str)
                self.assertTrue(arg_name)
                self.assertIn(injector_attr, known_attrs)
                self.assertTrue(hasattr(injector, injector_attr))

    def test_build_order_satisfies_constructor_dependencies(self):
        """Every provider dependency should be built by the time it is needed."""
        available = {"config", "logging_gateway"}

        for provider_name in di._PROVIDER_BUILD_ORDER:
            spec = di._PROVIDER_SPECS[provider_name]
            for _, injector_attr in spec.constructor_bindings:
                self.assertIn(
                    injector_attr,
                    available,
                    msg=(
                        f"{provider_name} depends on '{injector_attr}' before it is built"
                    ),
                )

            available.add(spec.injector_attr)
