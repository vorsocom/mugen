"""Unit tests for deterministic provider token resolution in mugen.core.di."""

import unittest

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway


# pylint: disable=protected-access
class TestDIProviderResolution(unittest.TestCase):
    """Unit tests for tokenized provider resolution rules."""

    def test_resolve_provider_class_rejects_module_class_and_unknown_token(self) -> None:
        with self.assertRaises(RuntimeError):
            di._resolve_provider_class(
                config={"mugen": {"modules": {"core": {"gateway": {"completion": None}}}}},
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_class(
                config={
                    "mugen": {
                        "modules": {
                            "core": {"gateway": {"completion": "module.path:Gateway"}}
                        }
                    }
                },
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )
        with self.assertRaises(RuntimeError):
            di._resolve_provider_class(
                config={
                    "mugen": {
                        "modules": {"core": {"gateway": {"completion": "unknown-token"}}}
                    }
                },
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )

    def test_completion_provider_uses_configured_token(self) -> None:
        """Build completion provider from explicit token configuration."""
        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "completion": "deterministic",
                        }
                    }
                }
            }
        }
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=unittest.mock.Mock(),
        )

        di._build_provider(config, injector, provider_name="completion_gateway")

        self.assertEqual(type(injector.completion_gateway).__name__, "DeterministicCompletionGateway")
