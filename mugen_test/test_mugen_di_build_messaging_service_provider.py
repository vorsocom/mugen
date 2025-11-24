"""Provides unit tests for mugen.core.di._build_messaging_service_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.service.messaging import IMessagingService


# pylint: disable=protected-access
class TestDIBuildMessagingService(unittest.TestCase):
    """Unit tests for mugen.core.di._build_messaging_service_provider."""

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

                # Attempt to build the Messaging service.
                di._build_messaging_service_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The operation cannot be completed since the
                # injector is incorrectly typed and "logger = injector.logging_gateway"
                # will fail.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid injector (messaging_service).",
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

                # Attempt to build the Messaging service.
                di._build_messaging_service_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The Messaging service cannot be configured since
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
                                "service": {
                                    "messaging": "nonexistent_module",
                                }
                            }
                        }
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the Messaging service.
                di._build_messaging_service_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The Messaging service module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (messaging_service).",
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
                    # Attempt to build the Messaging service.
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
                class DummyMessagingServiceClass(IMessagingService):
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
                    def cp_extensions(self):
                        pass

                    @property
                    def ct_extensions(self):
                        pass

                    @property
                    def ctx_extensions(self):
                        pass

                    @property
                    def mh_extensions(self):
                        pass

                    @property
                    def rag_extensions(self):
                        pass

                    @property
                    def rpp_extensions(self):
                        pass

                    async def handle_audio_message(
                        self,
                        platform: str,
                        room_id: str,
                        sender: str,
                        message: dict,
                    ) -> list[dict] | None:
                        pass

                    async def handle_file_message(
                        self,
                        platform: str,
                        room_id: str,
                        sender: str,
                        message: dict,
                    ) -> list[dict] | None:
                        pass

                    async def handle_image_message(
                        self,
                        platform: str,
                        room_id: str,
                        sender: str,
                        message: dict,
                    ) -> list[dict] | None:
                        pass

                    async def handle_text_message(
                        self,
                        platform: str,
                        room_id: str,
                        sender: str,
                        message: str,
                        message_context: list[str] = None,
                    ):
                        pass

                    async def handle_video_message(
                        self,
                        platform: str,
                        room_id: str,
                        sender: str,
                        message: dict,
                    ) -> list[dict] | None:
                        pass

                    def register_cp_extension(self, ext):
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

                sc = unittest.mock.Mock
                sc.return_value = [DummyMessagingServiceClass]

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
                    # Attempt to build the Messaging service.
                    di._build_messaging_service_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
