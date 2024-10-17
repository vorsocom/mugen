"""Provides unit tests for mugen.core.di._build_messaging_service_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.service.messaging import IMessagingService


# pylint: disable=protected-access
class TestDIBuildMessagingService(unittest.TestCase):
    """Unit tests for mugen.core.di._build_messaging_service_provider."""

    def test_module_configuration_unavailable(self):
        """Test effects of missing module configuration."""
        try:
            with self.assertLogs("root", level="ERROR") as logger:
                # Empty config.
                config = {}

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the messaging service.
                di._build_messaging_service_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The messaging service cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (messaging_service).",
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
                                "service": {
                                    "messaging": "nonexistent_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the messaging service.
                di._build_messaging_service_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The messaging service module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (messaging_service).",
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
                                "service": {
                                    "messaging": "valid_messaging_module",
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
                        "valid_messaging_module": unittest.mock.Mock(),
                    },
                ):
                    # Attempt to build the messaging service.
                    di._build_messaging_service_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since the
                    # injector is incorrectly typed and "config=injector.config"
                    # will fail.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Invalid injector (messaging_service).",
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
                                "service": {
                                    "messaging": "valid_messaging_module",
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
                            "valid_messaging_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.service.messaging.IMessagingService.__subclasses__"
                        ),
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the messaging service.
                    di._build_messaging_service_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since a valid
                    # subclass would not be found.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Valid subclass not found (messaging_service).",
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
                                "service": {
                                    "messaging": "valid_messaging_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses
                # pylint: disable=too-few-public-methods
                class DummyMessagingClass(IMessagingService):
                    """Dummy messaging class."""

                    def __init__(  # pylint: disable=too-many-arguments
                        self,
                        config,
                        completion_gateway,
                        keyval_storage_gateway,
                        logging_gateway,
                        user_service,
                    ):
                        pass

                    @property
                    def mh_extensions(self):
                        pass

                    async def handle_text_message(
                        self,
                        platform: str,
                        room_id: str,
                        sender: str,
                        content: str,
                    ):
                        pass

                    def add_message_to_thread(
                        self, message: str, role: str, room_id: str
                    ):
                        pass

                    def clear_attention_thread(self, room_id: str, keep: int = 0):
                        pass

                    def load_attention_thread(self, room_id: str):
                        pass

                    def save_attention_thread(self, room_id: str, thread: dict):
                        pass

                    def register_ct_extension(self, ext):
                        pass

                    def register_ctx_extension(self, ext):
                        pass

                    def register_mh_extension(self, ext):
                        pass

                    def register_rag_extension(self, ext):
                        pass

                    def register_rpp_extension(self, ext):
                        pass

                    def trigger_in_response(self, response: str, platform: str = None):
                        pass

                sc = unittest.mock.Mock
                sc.return_value = [DummyMessagingClass]

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_messaging_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.service.messaging.IMessagingService.__subclasses__"
                        ),
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the messaging service.
                    di._build_messaging_service_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
