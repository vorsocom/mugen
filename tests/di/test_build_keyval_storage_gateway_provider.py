"""Provides unit tests for mugen.core.di._build_keyval_storage_gateway_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway


# pylint: disable=protected-access
class TestDIBuildKeyValStorageGateway(unittest.TestCase):
    """Unit tests for mugen.core.di._build_keyval_storage_gateway_provider."""

    def test_module_configuration_unavailable(self):
        """Test effects of missing module configuration."""
        try:
            with self.assertLogs("root", level="ERROR") as logger:
                # Empty config.
                config = {}

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the key-value storage gateway.
                di._build_keyval_storage_gateway_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The key-value storage gateway cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (keyval_storage_gateway).",
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
                                    "storage": {
                                        "keyval": "nonexistent_module",
                                    }
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the key-value storage gateway.
                di._build_keyval_storage_gateway_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The key-value storage gateway module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (keyval_storage_gateway).",
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
                                    "storage": {
                                        "keyval": "valid_keyval_storage_module",
                                    }
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
                        "valid_keyval_storage_module": unittest.mock.Mock(),
                    },
                ):
                    # Attempt to build the key-value storage gateway.
                    di._build_keyval_storage_gateway_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since the
                    # injector is incorrectly typed and "config=injector.config"
                    # will fail.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Invalid injector (keyval_storage_gateway).",
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
                                    "storage": {
                                        "keyval": "valid_keyval_storage_module",
                                    }
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
                            "valid_keyval_storage_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.storage.keyval.IKeyValStorageGateway.__subclasses__",  # pylint: disable=line-too-long
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the key-value storage gateway.
                    di._build_keyval_storage_gateway_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since a valid
                    # subclass would not be found.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Valid subclass not found (keyval_storage_gateway).",
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
                                    "storage": {
                                        "keyval": "valid_keyval_storage_module",
                                    }
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses
                # pylint: disable=too-few-public-methods
                class DummyKeyValStorageClass(IKeyValStorageGateway):
                    """Dummy key-value storage class."""

                    def __init__(self, config, logging_gateway):
                        pass

                    def close(self):
                        pass

                    def get(self, key, decode=True):
                        pass

                    def has_key(self, key):
                        pass

                    def keys(self):
                        pass

                    def put(self, key, value):
                        pass

                    def remove(self, key):
                        pass

                sc = unittest.mock.Mock
                sc.return_value = [DummyKeyValStorageClass]

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_keyval_storage_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.storage.keyval.IKeyValStorageGateway.__subclasses__",  # pylint: disable=line-too-long
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the key-value storage gateway.
                    di._build_keyval_storage_gateway_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
