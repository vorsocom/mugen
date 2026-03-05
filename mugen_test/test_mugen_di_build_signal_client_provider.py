"""Provides unit tests for mugen.core.di._build_signal_client_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.client.signal import ISignalClient


# pylint: disable=protected-access
class TestDIBuildSignalClient(unittest.TestCase):
    """Unit tests for mugen.core.di._build_provider (signal_client)."""

    def test_incorrectly_typed_injector(self) -> None:
        config = {
            "mugen": {
                "platforms": ["signal"],
                "modules": {
                    "core": {
                        "client": {
                            "signal": "default",
                        }
                    }
                },
            }
        }

        with self.assertLogs("root", level="ERROR") as logger:
            di._build_provider(config, None, provider_name="signal_client")

        self.assertEqual(
            logger.output[0],
            "ERROR:root:Invalid injector (signal_client).",
        )

    def test_platform_inactive(self) -> None:
        config = {
            "mugen": {
                "platforms": [],
            }
        }
        injector = di.injector.DependencyInjector()

        with self.assertLogs("root", level="WARNING") as logger:
            di._build_provider(config, injector, provider_name="signal_client")

        self.assertEqual(
            logger.output[1],
            "WARNING:root:Signal platform not active. Client not loaded.",
        )

    def test_module_configuration_unavailable(self) -> None:
        config = {
            "mugen": {
                "platforms": ["signal"],
            }
        }
        injector = di.injector.DependencyInjector()

        with self.assertLogs("root", level="ERROR") as logger:
            di._build_provider(config, injector, provider_name="signal_client")

        self.assertEqual(
            logger.output[0],
            "ERROR:root:Invalid configuration (signal_client).",
        )

    def test_normal_execution(self) -> None:
        config = {
            "mugen": {
                "platforms": ["signal"],
                "modules": {
                    "core": {
                        "client": {
                            "signal": "default",
                        }
                    }
                },
            }
        }
        injector = di.injector.DependencyInjector(
            config=object(),
            ipc_service=object(),
            keyval_storage_gateway=object(),
            logging_gateway=unittest.mock.Mock(),
            messaging_service=object(),
            user_service=object(),
        )

        class DummySignalClientClass(ISignalClient):
            def __init__(  # pylint: disable=too-many-arguments
                self,
                config,
                ipc_service,
                keyval_storage_gateway,
                logging_gateway,
                messaging_service,
                user_service,
            ):
                _ = (
                    config,
                    ipc_service,
                    keyval_storage_gateway,
                    logging_gateway,
                    messaging_service,
                    user_service,
                )

            async def init(self) -> None:
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def receive_events(self):
                if False:
                    yield {}
                return

            async def send_text_message(
                self,
                *,
                recipient: str,
                text: str,
            ) -> dict | None:
                _ = (recipient, text)
                return None

            async def send_media_message(
                self,
                *,
                recipient: str,
                message: str | None = None,
                base64_attachments: list[str] | None = None,
            ) -> dict | None:
                _ = (recipient, message, base64_attachments)
                return None

            async def send_reaction(
                self,
                *,
                recipient: str,
                reaction: str,
                target_author: str,
                timestamp: int,
                remove: bool = False,
            ) -> dict | None:
                _ = (recipient, reaction, target_author, timestamp, remove)
                return None

            async def send_receipt(
                self,
                *,
                recipient: str,
                receipt_type: str,
                timestamp: int,
            ) -> dict | None:
                _ = (recipient, receipt_type, timestamp)
                return None

            async def emit_processing_signal(
                self,
                recipient: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                _ = (recipient, state, message_id)
                return True

            async def download_attachment(self, attachment_id: str) -> dict | None:
                _ = attachment_id
                return None

        with (
            unittest.mock.patch(
                target="mugen.core.di.resolve_provider_class",
                return_value=DummySignalClientClass,
            ),
            self.assertNoLogs("root", level="ERROR"),
        ):
            di._build_provider(config, injector, provider_name="signal_client")

        self.assertIsInstance(injector.signal_client, DummySignalClientClass)
