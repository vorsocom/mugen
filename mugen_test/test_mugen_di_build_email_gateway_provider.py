"""Provides unit tests for mugen.core.di._build_email_gateway_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.gateway.email import IEmailGateway


# pylint: disable=protected-access
class TestDIBuildEmailGateway(unittest.TestCase):
    """Unit tests for mugen.core.di._build_email_gateway_provider."""

    def test_incorrectly_typed_injector(self):
        """Test effects of an incorrectly typed injector."""
        try:
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="ERROR") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                config = {}
                injector = None

                di._build_provider(config, injector, provider_name="email_gateway")

                self.assertEqual(logger.records[0].name, "root")
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid injector (email_gateway).",
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_module_configuration_unavailable(self):
        """Test effects of missing module configuration."""
        try:
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="WARNING") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                config = {}
                injector = di.injector.DependencyInjector()

                di._build_provider(config, injector, provider_name="email_gateway")

                self.assertEqual(logger.records[0].name, "root")
                self.assertIn(
                    "WARNING:root:Using root logger (email_gateway).",
                    logger.output,
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_module_import_failure(self):
        """Test effects of module import failure."""
        try:
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="WARNING") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "email": "nonexistent_module:MissingClass",
                                }
                            }
                        }
                    }
                }
                injector = di.injector.DependencyInjector()

                di._build_provider(config, injector, provider_name="email_gateway")

                self.assertEqual(logger.records[0].name, "root")
                self.assertIn(
                    "WARNING:root:Using root logger (email_gateway).",
                    logger.output,
                )
                self.assertIn(
                    "WARNING:root:Invalid configuration (email_gateway): module:Class paths are not supported.",
                    logger.output,
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_valid_subclass_not_found(self):
        """Test effects of invalid subclass import."""
        try:
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="WARNING") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "email": "valid_email_module:MissingClass",
                                }
                            }
                        }
                    }
                }
                injector = di.injector.DependencyInjector()

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_email_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.email.IEmailGateway.__subclasses__",  # pylint: disable=line-too-long
                        return_value=[],
                    ),
                ):
                    di._build_provider(config, injector, provider_name="email_gateway")

                    self.assertEqual(logger.records[0].name, "root")
                    self.assertIn(
                        "WARNING:root:Using root logger (email_gateway).",
                        logger.output,
                    )
                    self.assertIn(
                        "WARNING:root:Invalid configuration (email_gateway): module:Class paths are not supported.",
                        logger.output,
                    )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_normal_execution(self):
        """Test normal execution with correct configuration and injector."""
        try:
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertNoLogs("root", level="ERROR"),
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "email": "valid_email_module:DummyEmailGatewayClass",
                                }
                            }
                        }
                    }
                }

                injector = di.injector.DependencyInjector()

                class DummyEmailGatewayClass(IEmailGateway):
                    """Dummy email class."""

                    def __init__(self, config, logging_gateway):
                        pass

                    async def check_readiness(self):
                        pass

                    async def send_email(self, request):
                        pass

                DummyEmailGatewayClass.__module__ = "valid_email_module"

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_email_module": unittest.mock.Mock(DummyEmailGatewayClass=DummyEmailGatewayClass),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.email.IEmailGateway.__subclasses__",  # pylint: disable=line-too-long
                        return_value=[DummyEmailGatewayClass],
                    ),
                    unittest.mock.patch(
                        target="mugen.core.di.resolve_provider_class",
                        return_value=DummyEmailGatewayClass,
                    ),
                ):
                    di._build_provider(config, injector, provider_name="email_gateway")

                self.assertIsInstance(injector.email_gateway, DummyEmailGatewayClass)
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")
