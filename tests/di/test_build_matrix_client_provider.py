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

                # Attempt to build the IPC service.
                di._build_matrix_client_provider(config, injector)

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

                # Attempt to build the IPC service.
                di._build_matrix_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The IPC service cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[1],
                    "WARNING:root:Matrix platform not active. Client not loaded.",
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

                # Attempt to build the IPC service.
                di._build_matrix_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The IPC service cannot be configured since
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
                                    "matrix": "nonexistent_module",
                                }
                            }
                        },
                        "platforms": ["matrix"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the IPC service.
                di._build_matrix_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The IPC service module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (matrix_client).",
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
                                    "matrix": "valid_matrix_module",
                                }
                            }
                        },
                        "platforms": ["matrix"],
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
                            "valid_matrix_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.client.matrix.IMatrixClient.__subclasses__"
                        ),
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the IPC service.
                    di._build_matrix_client_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since a valid
                    # subclass would not be found.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Valid subclass not found (matrix_client).",
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
                                    "matrix": "valid_matrix_module",
                                }
                            }
                        },
                        "platforms": ["matrix"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses
                # pylint: disable=too-few-public-methods
                class DummyMatrixClientClass(IMatrixClient):
                    """Dummy IPC class."""

                    def __init__(  # pylint: disable=too-many-arguments
                        self,
                        config,
                        ipc_service,
                        keyval_storage_gateway,
                        logging_gateway,
                        messaging_service,
                        user_service,
                    ):
                        pass

                    async def __aenter__(self):
                        pass

                    async def __aexit__(self, exc_type, exc_val, exc_tb):
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

                sc = unittest.mock.Mock
                sc.return_value = [DummyMatrixClientClass]

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
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the IPC service.
                    di._build_matrix_client_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
