"""Unit tests for provider class resolution in mugen.core.di."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.gateway.completion import ICompletionGateway


# pylint: disable=protected-access
class TestDIProviderResolution(unittest.TestCase):
    """Unit tests for module-aware provider class resolution."""

    def test_prefers_matching_module_when_multiple_subclasses(self):
        """Pick the class whose __module__ matches configured module."""

        class FirstCompletionGateway(ICompletionGateway):
            async def get_completion(self, context, operation="completion"):
                return None

        class SecondCompletionGateway(ICompletionGateway):
            async def get_completion(self, context, operation="completion"):
                return None

        FirstCompletionGateway.__module__ = "module.one"
        SecondCompletionGateway.__module__ = "module.two"

        logger = unittest.mock.Mock()
        subclasses = unittest.mock.Mock
        subclasses.return_value = [FirstCompletionGateway, SecondCompletionGateway]
        with unittest.mock.patch(
            "mugen.core.contract.gateway.completion.ICompletionGateway.__subclasses__",
            new_callable=subclasses,
        ):
            resolved = di._get_provider_class(
                interface=ICompletionGateway,
                module_name="module.two",
                provider_name="completion_gateway",
                logger=logger,
            )

        self.assertIs(resolved, SecondCompletionGateway)

    def test_single_subclass_without_module_match_returns_none(self):
        """Return None when subclass module does not match config."""

        class OnlyCompletionGateway(ICompletionGateway):
            async def get_completion(self, context, operation="completion"):
                return None

        OnlyCompletionGateway.__module__ = "other.module"

        logger = unittest.mock.Mock()
        subclasses = unittest.mock.Mock
        subclasses.return_value = [OnlyCompletionGateway]
        with unittest.mock.patch(
            "mugen.core.contract.gateway.completion.ICompletionGateway.__subclasses__",
            new_callable=subclasses,
        ):
            resolved = di._get_provider_class(
                interface=ICompletionGateway,
                module_name="configured.module",
                provider_name="completion_gateway",
                logger=logger,
            )

        self.assertIsNone(resolved)

    def test_completion_provider_uses_configured_module_class(self):
        """Build completion provider using configured module class."""

        class WrongCompletionGateway(ICompletionGateway):
            def __init__(self, config, logging_gateway):  # pylint: disable=unused-argument
                raise AssertionError("Wrong completion gateway selected.")

            async def get_completion(self, context, operation="completion"):
                return None

        class RightCompletionGateway(ICompletionGateway):
            def __init__(self, config, logging_gateway):  # pylint: disable=unused-argument
                pass

            async def get_completion(self, context, operation="completion"):
                return None

        WrongCompletionGateway.__module__ = "module.wrong"
        RightCompletionGateway.__module__ = "module.right"

        config = {
            "mugen": {
                "modules": {
                    "core": {
                        "gateway": {
                            "completion": "module.right",
                        }
                    }
                }
            }
        }
        injector = di.injector.DependencyInjector()
        subclasses = unittest.mock.Mock
        subclasses.return_value = [WrongCompletionGateway, RightCompletionGateway]

        with (
            unittest.mock.patch.dict(
                "sys.modules",
                {
                    "module.right": unittest.mock.Mock(),
                },
            ),
            unittest.mock.patch(
                "mugen.core.contract.gateway.completion.ICompletionGateway.__subclasses__",
                new_callable=subclasses,
            ),
        ):
            di._build_completion_gateway_provider(config, injector)

        self.assertIsInstance(injector.completion_gateway, RightCompletionGateway)
