"""Provides unit tests for mugen.core.di._build_keyval_storage_gateway_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway


# pylint: disable=protected-access
class TestDIBuildKeyValStorageGateway(unittest.TestCase):
    """Unit tests for mugen.core.di._build_keyval_storage_gateway_provider."""

    def test_incorrectly_typed_injector(self):
        """Test effects of an incorrectly typed injector."""
        try:
            # Replacement config loader that does
            # not load the application config file.
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="ERROR") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                # Logging config.
                config = {}

                # New injector
                injector = None

                # Attempt to build the key-value storage gateway.
                di._build_provider(
                    config, injector, provider_name="keyval_storage_gateway"
                )

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The operation cannot be completed since the
                # injector is incorrectly typed and "logger = injector.logging_gateway"
                # will fail.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid injector (keyval_storage_gateway).",
                )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_module_configuration_unavailable(self):
        """Test effects of missing module configuration."""
        try:
            # Replacement config loader that does
            # not load the application config file.
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="ERROR") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                # Empty config.
                config = {}

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the key-value storage gateway.
                di._build_provider(
                    config, injector, provider_name="keyval_storage_gateway"
                )

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
            # Replacement config loader that does
            # not load the application config file.
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="ERROR") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
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
                di._build_provider(
                    config, injector, provider_name="keyval_storage_gateway"
                )

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

    def test_valid_subclass_not_found(self):
        """Test effects of invalid subclass import."""
        try:
            # Replacement config loader that does
            # not load the application config file.
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="ERROR") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
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

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_keyval_storage_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.storage.keyval.IKeyValStorageGateway.__subclasses__",  # pylint: disable=line-too-long
                        return_value=[],
                    ),
                ):
                    # Attempt to build the key-value storage gateway.
                    di._build_provider(
                        config, injector, provider_name="keyval_storage_gateway"
                    )

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

    def test_normal_execution(self):
        """Test normal execution with correct configuration and injector."""
        try:
            # Replacement config loader that does
            # not load the application config file.
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                # No logs expected.
                self.assertNoLogs("root", level="ERROR"),
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
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
                class DummyKeyValStorageGatewayClass(IKeyValStorageGateway):
                    """Dummy key-value storage class."""

                    def __init__(self, config, logging_gateway):
                        pass

                    async def aclose(self):
                        pass

                    async def get_entry(
                        self,
                        key,
                        *,
                        namespace=None,
                        include_expired=False,
                    ):
                        pass

                    async def put_bytes(
                        self,
                        key,
                        value,
                        *,
                        namespace=None,
                        codec="bytes",
                        expected_row_version=None,
                        ttl_seconds=None,
                    ):
                        pass

                    async def delete(
                        self,
                        key,
                        *,
                        namespace=None,
                        expected_row_version=None,
                    ):
                        pass

                    async def exists(self, key, *, namespace=None):
                        pass

                    async def list_keys(
                        self,
                        *,
                        prefix="",
                        namespace=None,
                        limit=None,
                        cursor=None,
                    ):
                        pass

                    async def compare_and_set(
                        self,
                        key,
                        value,
                        *,
                        namespace=None,
                        codec="bytes",
                        expected_row_version=0,
                        ttl_seconds=None,
                    ):
                        pass

                DummyKeyValStorageGatewayClass.__module__ = (
                    "valid_keyval_storage_module"
                )


                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_keyval_storage_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target="mugen.core.contract.gateway.storage.keyval.IKeyValStorageGateway.__subclasses__",  # pylint: disable=line-too-long
                        return_value=[DummyKeyValStorageGatewayClass],
                    ),
                ):
                    # Attempt to build the key-value storage gateway.
                    di._build_provider(
                        config, injector, provider_name="keyval_storage_gateway"
                    )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
