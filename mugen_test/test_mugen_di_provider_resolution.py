"""Unit tests for deterministic provider class resolution in mugen.core.di."""

from types import ModuleType
import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway


# pylint: disable=protected-access
class TestDIProviderResolution(unittest.TestCase):
    """Unit tests for module:Class provider resolution rules."""

    def test_split_class_path_requires_module_class_syntax(self) -> None:
        with self.assertRaises(RuntimeError):
            di._split_class_path(None, provider_name="completion_gateway")
        with self.assertRaises(RuntimeError):
            di._split_class_path("module.only", provider_name="completion_gateway")
        with self.assertRaises(RuntimeError):
            di._split_class_path("module:", provider_name="completion_gateway")

        module_name, class_name = di._split_class_path(
            "module.path:ProviderClass",
            provider_name="completion_gateway",
        )
        self.assertEqual(module_name, "module.path")
        self.assertEqual(class_name, "ProviderClass")

    def test_resolve_provider_class_requires_existing_subclass(self) -> None:
        class NotACompletionGateway:  # pylint: disable=too-few-public-methods
            pass

        fake_module = ModuleType("module.invalid")
        fake_module.NotACompletionGateway = NotACompletionGateway

        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "completion": "module.invalid:NotACompletionGateway",
                        }
                    }
                }
            }
        }
        with (
            unittest.mock.patch.dict("sys.modules", {"module.invalid": fake_module}),
            self.assertRaises(RuntimeError),
        ):
            di._resolve_provider_class(
                config=config,
                provider_name="completion_gateway",
                module_path=("mugen", "modules", "core", "gateway", "completion"),
                interface=ICompletionGateway,
            )

    def test_completion_provider_uses_configured_module_class(self) -> None:
        """Build completion provider from explicit module:Class configuration."""

        class RightCompletionGateway(ICompletionGateway):
            def __init__(self, config, logging_gateway):  # noqa: ARG002
                pass

            async def check_readiness(self) -> None:
                return None

            async def get_completion(self, request):
                return None

        fake_module = ModuleType("module.right")
        fake_module.RightCompletionGateway = RightCompletionGateway

        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "completion": "module.right:RightCompletionGateway",
                        }
                    }
                }
            }
        }
        injector = di.injector.DependencyInjector(
            config=object(),
            logging_gateway=unittest.mock.Mock(),
        )

        with unittest.mock.patch.dict("sys.modules", {"module.right": fake_module}):
            di._build_provider(config, injector, provider_name="completion_gateway")

        self.assertIsInstance(injector.completion_gateway, RightCompletionGateway)
