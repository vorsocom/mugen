"""Provides unit tests for mugen.core.di._build_logging_gateway_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.gateway.logging import ILoggingGateway


# pylint: disable=protected-access
class TestDIBuildLoggingGateway(unittest.TestCase):
    """Unit tests for mugen.core.di._build_logging_gateway_provider."""

    def test_module_configuration_unavailable(self):
        """Test effects of missing module configuration."""
        try:
            with self.assertLogs("root", level="ERROR") as logger:
                # Empty config.
                config = {}

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the logging gateway.
                di._build_logging_gateway_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The logging gateway cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (logging_gateway).",
                )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_module_import_failure(self):
        """Test effects of module import failure."""
        try:
            with self.assertLogs("root", level="ERROR") as logger:
                # Logging config.
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "logging": "nonexistent_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the logging gateway.
                di._build_logging_gateway_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The logging gateway module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (logging_gateway).",
                )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_incorrectly_typed_injector(self):
        """Test effects of an incorrectly typed injector."""
        try:
            with self.assertLogs("root", level="ERROR") as logger:
                # Logging config.
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "logging": "valid_logging_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = None

                with unittest.mock.patch.dict(
                    "sys.modules",
                    {
                        "valid_logging_module": unittest.mock.Mock(),
                    },
                ):
                    # Attempt to build the logging gateway.
                    di._build_logging_gateway_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since the
                    # injector is incorrectly typed and "config=injector.config"
                    # will fail.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Invalid injector (logging_gateway).",
                    )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_valid_subclass_not_found(self):
        """Test effects of invalid subclass import."""
        try:
            with self.assertLogs("root", level="ERROR") as logger:
                # Logging config.
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "logging": "valid_logging_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses
                sc = unittest.mock.Mock
                sc.return_value = []

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_logging_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.logging.ILoggingGateway.__subclasses__",
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the logging gateway.
                    di._build_logging_gateway_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since a valid
                    # subclass of ILoggingGateway would not be found.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Valid subclass not found (logging_gateway).",
                    )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_valid_subclass_available(self):
        """Test effects of a valid subclass being available."""
        try:
            # No logs expected.
            with self.assertNoLogs("root", level="ERROR"):
                # Logging config.
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "logging": "valid_logging_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses
                class DummyLoggingGatewayClass(ILoggingGateway):
                    """Dummy logging class."""

                    def __init__(self, config: dict):
                        pass

                    def critical(self, message):
                        pass

                    def debug(self, message):
                        pass

                    def error(self, message):
                        pass

                    def info(self, message):
                        pass

                    def warning(self, message):
                        pass

                sc = unittest.mock.Mock
                sc.return_value = [DummyLoggingGatewayClass]

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_logging_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.logging.ILoggingGateway.__subclasses__",
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the logging gateway.
                    di._build_logging_gateway_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
