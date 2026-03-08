"""Provides unit tests for mugen.core.di._build_matrix_client_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.client.matrix import IMatrixClient


# pylint: disable=protected-access
class TestDIBuildMatrixClient(unittest.TestCase):
    """Unit tests for mugen.core.di._build_matrix_client_provider."""

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

                # Attempt to build the Matrix service.
                di._build_provider(config, injector, provider_name="matrix_client")

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The operation cannot be completed since the
                # injector is incorrectly typed and "logger = injector.logging_gateway"
                # will fail.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid injector (matrix_client).",
                )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_platform_inactive(self):
        """Test effects of platform not being activated."""
        try:
            # Replacement config loader that does
            # not load the application config file.
            _load_config = unittest.mock.Mock()
            _load_config.return_value = {}

            with (
                self.assertLogs("root", level="WARNING") as logger,
                unittest.mock.patch(
                    target="mugen.core.di._load_config",
                    new_callable=_load_config,
                ),
            ):
                # Empty config.
                config = {
                    "mugen": {
                        "platforms": [],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()
                injector.ingress_service = unittest.mock.Mock()

                # Attempt to build the Matrix service.
                di._build_provider(config, injector, provider_name="matrix_client")

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The Matrix service cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[1],
                    "WARNING:root:Matrix platform not active. Client not loaded.",
                )
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")

    def test_platform_configuration_unavailable(self):
        """Test effects of missing platform configuration."""
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
                config = {
                    "mugen": {},
                }

                injector = di.injector.DependencyInjector()

                di._build_provider(config, injector, provider_name="matrix_client")

                self.assertEqual(logger.records[0].name, "root")
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (matrix_client).",
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
                config = {
                    "mugen": {
                        "platforms": ["matrix"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the Matrix service.
                di._build_provider(config, injector, provider_name="matrix_client")

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The Matrix service cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (matrix_client).",
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
                                "client": {
                                    "matrix": "nonexistent_module:MissingClass",
                                }
                            }
                        },
                        "platforms": ["matrix"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the Matrix service.
                di._build_provider(config, injector, provider_name="matrix_client")

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The Matrix service module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (matrix_client): module:Class paths are not supported.",
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
                                "client": {
                                    "matrix": "valid_matrix_module:MissingClass",
                                }
                            }
                        },
                        "platforms": ["matrix"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_matrix_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.client.matrix.IMatrixClient.__subclasses__"
                        ),
                        return_value=[],
                    ),
                ):
                    # Attempt to build the Matrix service.
                    di._build_provider(config, injector, provider_name="matrix_client")

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since a valid
                    # subclass would not be found.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Invalid configuration (matrix_client): module:Class paths are not supported.",
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
                                "client": {
                                    "matrix": "valid_matrix_module:DummyMatrixClientClass",
                                }
                            }
                        },
                        "platforms": ["matrix"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()
                injector.ingress_service = unittest.mock.Mock()

                # Dummy subclasses
                class DummyMatrixClientClass(IMatrixClient):
                    """Dummy Matrix class."""

                    def __init__(  # pylint: disable=too-many-arguments
                        self,
                        config,
                        ipc_service,
                        ingress_service,
                        keyval_storage_gateway,
                        relational_storage_gateway,
                        logging_gateway,
                        messaging_service,
                        user_service,
                    ):
                        _ = (
                            config,
                            ipc_service,
                            ingress_service,
                            keyval_storage_gateway,
                            relational_storage_gateway,
                            logging_gateway,
                            messaging_service,
                            user_service,
                        )

                    async def __aenter__(self):
                        pass

                    async def __aexit__(self, exc_type, exc_val, exc_tb):
                        pass

                    async def close(self):
                        pass

                    @property
                    def sync_token(self):
                        pass

                    def cleanup_known_user_devices_list(self):
                        pass

                    def trust_known_user_devices(self):
                        pass

                    def verify_user_devices(self, user_id):
                        pass

                    async def sync_forever(
                        self,
                        *,
                        since=None,
                        timeout=100,
                        full_state=True,
                        set_presence="online",
                    ):
                        _ = (since, timeout, full_state, set_presence)
                        return None

                    async def get_profile(self, user_id=None):
                        _ = user_id
                        return None

                    async def set_displayname(self, displayname):
                        _ = displayname
                        return None

                    async def monitor_runtime_health(self):
                        return None

                DummyMatrixClientClass.__module__ = "valid_matrix_module"

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_matrix_module": unittest.mock.Mock(
                                DummyMatrixClientClass=DummyMatrixClientClass
                            ),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.client.matrix.IMatrixClient.__subclasses__"
                        ),
                        return_value=[DummyMatrixClientClass],
                    ),
                    unittest.mock.patch(
                        target="mugen.core.di.resolve_provider_class",
                        return_value=DummyMatrixClientClass,
                    ),
                ):
                    # Attempt to build the Matrix service.
                    di._build_provider(config, injector, provider_name="matrix_client")
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
