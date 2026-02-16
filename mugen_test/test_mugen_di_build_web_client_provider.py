"""Provides unit tests for mugen.core.di._build_web_client_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.client.web import IWebClient


# pylint: disable=protected-access
class TestDIBuildWebClient(unittest.TestCase):
    """Unit tests for mugen.core.di._build_web_client_provider."""

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

                di._build_provider(config, injector, provider_name="web_client")

                self.assertEqual(logger.records[0].name, "root")
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid injector (web_client).",
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_platform_inactive(self):
        """Test effects of platform not being activated."""
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
                        "platforms": [],
                    }
                }
                injector = di.injector.DependencyInjector()

                di._build_provider(config, injector, provider_name="web_client")

                self.assertEqual(logger.records[0].name, "root")
                self.assertEqual(
                    logger.output[1],
                    "WARNING:root:Web platform not active. Client not loaded.",
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_module_configuration_unavailable(self):
        """Test effects of missing module configuration."""
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
                config = {
                    "mugen": {
                        "platforms": ["web"],
                    }
                }
                injector = di.injector.DependencyInjector()

                di._build_provider(config, injector, provider_name="web_client")

                self.assertEqual(logger.records[0].name, "root")
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Invalid configuration (web_client).",
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_module_import_failure(self):
        """Test effects of module import failure."""
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
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "client": {
                                    "web": "nonexistent_module",
                                }
                            }
                        },
                        "platforms": ["web"],
                    }
                }
                injector = di.injector.DependencyInjector()

                di._build_provider(config, injector, provider_name="web_client")

                self.assertEqual(logger.records[0].name, "root")
                self.assertEqual(
                    logger.output[0],
                    "ERROR:root:Could not import module (web_client).",
                )
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")

    def test_valid_subclass_not_found(self):
        """Test effects of invalid subclass import."""
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
                config = {
                    "mugen": {
                        "modules": {
                            "core": {
                                "client": {
                                    "web": "valid_web_module",
                                }
                            }
                        },
                        "platforms": ["web"],
                    }
                }
                injector = di.injector.DependencyInjector()

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_web_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(
                            "mugen.core.contract.client.web.IWebClient.__subclasses__"
                        ),
                        return_value=[],
                    ),
                ):
                    di._build_provider(config, injector, provider_name="web_client")

                    self.assertEqual(logger.records[0].name, "root")
                    self.assertEqual(
                        logger.output[0],
                        "ERROR:root:Valid subclass not found (web_client).",
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
                                "client": {
                                    "web": "valid_web_module",
                                }
                            }
                        },
                        "platforms": ["web"],
                    }
                }
                injector = di.injector.DependencyInjector()

                class DummyWebClientClass(IWebClient):
                    """Dummy web client class."""

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

                    async def init(self):
                        pass

                    async def close(self):
                        pass

                    async def enqueue_message(  # pylint: disable=too-many-arguments
                        self,
                        *,
                        auth_user: str,
                        conversation_id: str,
                        message_type: str,
                        text: str | None = None,
                        metadata: dict | None = None,
                        file_path: str | None = None,
                        mime_type: str | None = None,
                        original_filename: str | None = None,
                        client_message_id: str | None = None,
                    ) -> dict:
                        pass

                    async def stream_events(
                        self,
                        *,
                        auth_user: str,
                        conversation_id: str,
                        last_event_id: str | None = None,
                    ):
                        pass

                    async def resolve_media_download(
                        self,
                        *,
                        auth_user: str,
                        token: str,
                    ) -> dict | None:
                        pass

                DummyWebClientClass.__module__ = "valid_web_module"

                with (
                    unittest.mock.patch.dict(
                        "sys.modules",
                        {
                            "valid_web_module": unittest.mock.Mock(),
                        },
                    ),
                    unittest.mock.patch(
                        target=(
                            "mugen.core.contract.client.web.IWebClient.__subclasses__"
                        ),
                        return_value=[DummyWebClientClass],
                    ),
                ):
                    di._build_provider(config, injector, provider_name="web_client")
        except:  # pylint: disable=bare-except
            self.fail("Exception raised unexpectedly.")
