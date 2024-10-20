"""Provides unit tests for mugen.core.di._build_whatsapp_client_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.client.whatsapp import IWhatsAppClient


# pylint: disable=protected-access
class TestDIBuildWhatsAppClient(unittest.TestCase):
    """Unit tests for mugen.core.di._build_whatsapp_client_provider."""

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

                # Attempt to build the WhatsApp service.
                di._build_whatsapp_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The operation cannot be completed since the
                # injector is incorrectly typed and "logger = injector.logging_gateway"
                # will fail.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid injector (whatsapp_client).",
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

                # Attempt to build the WhatsApp service.
                di._build_whatsapp_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The WhatsApp service cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[1],
                    "WARNING:root:WhatsApp platform not active. Client not loaded.",
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
                        "platforms": ["whatsapp"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the WhatsApp service.
                di._build_whatsapp_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The WhatsApp service cannot be configured since
                # there is no configuration specifying the module.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (whatsapp_client).",
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
                                    "whatsapp": "nonexistent_module",
                                }
                            }
                        },
                        "platforms": ["whatsapp"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Attempt to build the WhatsApp service.
                di._build_whatsapp_client_provider(config, injector)

                # The root logger should be used since the name
                # of the muGen logger is not available from the
                # config.
                self.assertEqual(logger.records[0].name, "root")

                # The WhatsApp service module cannot be imported
                # since a nonexistent module was supplied.
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (whatsapp_client).",
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
                                    "whatsapp": "valid_whatsapp_module",
                                }
                            }
                        },
                        "platforms": ["whatsapp"],
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
                            "valid_whatsapp_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.client.whatsapp.IWhatsAppClient.__subclasses__"
                        ),
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the WhatsApp service.
                    di._build_whatsapp_client_provider(config, injector)

                    # The root logger should be used since the name
                    # of the muGen logger is not available from the
                    # config.
                    self.assertEqual(logger.records[0].name, "root")

                    # The operation cannot be completed since a valid
                    # subclass would not be found.
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Valid subclass not found (whatsapp_client).",
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
                                    "whatsapp": "valid_whatsapp_module",
                                }
                            }
                        },
                        "platforms": ["whatsapp"],
                    }
                }

                # New injector
                injector = di.injector.DependencyInjector()

                # Dummy subclasses
                # pylint: disable=too-few-public-methods
                class DummyWhatsAppClientClass(IWhatsAppClient):
                    """Dummy WhatsApp class."""

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

                    async def init(self):
                        pass

                    async def close(self):
                        pass

                    async def delete_media(self, media_id: str):
                        pass

                    async def download_media(self, media_url: str):
                        pass

                    async def retrieve_media_url(self, media_id: str):
                        pass

                    async def send_audio_message(
                        self,
                        audio: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_contacts_message(
                        self,
                        contacts: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_document_message(
                        self,
                        document: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_image_message(
                        self,
                        image: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_interactive_message(
                        self,
                        interactive: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_location_message(
                        self,
                        location: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_reaction_message(
                        self, reaction: dict, recipient: str
                    ) -> str | None:
                        pass

                    async def send_sticker_message(
                        self,
                        sticker: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_template_message(
                        self,
                        template: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_text_message(
                        self,
                        message: str,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def send_video_message(
                        self,
                        video: dict,
                        recipient: str,
                        reply_to: str = None,
                    ):
                        pass

                    async def upload_media(
                        self,
                        file_path: str,
                        file_type: str,
                    ):
                        pass

                sc = unittest.mock.Mock
                sc.return_value = [DummyWhatsAppClientClass]

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_whatsapp_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(  # pylint: disable=line-too-long
                            "mugen.core.contract.client.whatsapp.IWhatsAppClient.__subclasses__"
                        ),
                        new_callable=sc,
                    ),
                ):
                    # Attempt to build the WhatsApp service.
                    di._build_whatsapp_client_provider(config, injector)
        except:  # pylint: disable=bare-except
            # We should not get here because all exceptions
            # should be handled in the called function.
            self.fail("Exception raised unexpectedly.")
