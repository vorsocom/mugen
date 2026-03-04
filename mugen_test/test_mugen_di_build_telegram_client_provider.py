"""Provides unit tests for mugen.core.di._build_telegram_client_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.client.telegram import ITelegramClient


# pylint: disable=protected-access
class TestDIBuildTelegramClient(unittest.TestCase):
    """Unit tests for mugen.core.di._build_provider (telegram_client)."""

    def test_incorrectly_typed_injector(self) -> None:
        config = {
            "mugen": {
                "platforms": ["telegram"],
                "modules": {
                    "core": {
                        "client": {
                            "telegram": "default",
                        }
                    }
                },
            }
        }

        with self.assertLogs("root", level="ERROR") as logger:
            di._build_provider(config, None, provider_name="telegram_client")

        self.assertEqual(
            logger.output[0],
            "ERROR:root:Invalid injector (telegram_client).",
        )

    def test_platform_inactive(self) -> None:
        config = {
            "mugen": {
                "platforms": [],
            }
        }
        injector = di.injector.DependencyInjector()

        with self.assertLogs("root", level="WARNING") as logger:
            di._build_provider(config, injector, provider_name="telegram_client")

        self.assertEqual(
            logger.output[1],
            "WARNING:root:Telegram platform not active. Client not loaded.",
        )

    def test_module_configuration_unavailable(self) -> None:
        config = {
            "mugen": {
                "platforms": ["telegram"],
            }
        }
        injector = di.injector.DependencyInjector()

        with self.assertLogs("root", level="ERROR") as logger:
            di._build_provider(config, injector, provider_name="telegram_client")

        self.assertEqual(
            logger.output[0],
            "ERROR:root:Invalid configuration (telegram_client).",
        )

    def test_normal_execution(self) -> None:
        config = {
            "mugen": {
                "platforms": ["telegram"],
                "modules": {
                    "core": {
                        "client": {
                            "telegram": "default",
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

        class DummyTelegramClientClass(ITelegramClient):
            def __init__(
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
                ...

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                ...

            async def send_text_message(
                self,
                *,
                chat_id: str,
                text: str,
                reply_markup: dict | None = None,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, text, reply_markup, reply_to_message_id)
                return None

            async def send_audio_message(
                self,
                *,
                chat_id: str,
                audio: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, audio, reply_to_message_id)
                return None

            async def send_file_message(
                self,
                *,
                chat_id: str,
                document: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, document, reply_to_message_id)
                return None

            async def send_image_message(
                self,
                *,
                chat_id: str,
                photo: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, photo, reply_to_message_id)
                return None

            async def send_video_message(
                self,
                *,
                chat_id: str,
                video: dict,
                reply_to_message_id: int | None = None,
            ) -> dict | None:
                _ = (chat_id, video, reply_to_message_id)
                return None

            async def answer_callback_query(
                self,
                *,
                callback_query_id: str,
                text: str | None = None,
                show_alert: bool | None = None,
            ) -> dict | None:
                _ = (callback_query_id, text, show_alert)
                return None

            async def emit_processing_signal(
                self,
                chat_id: str,
                *,
                state: str,
                message_id: str | None = None,
            ) -> bool | None:
                _ = (chat_id, state, message_id)
                return True

            async def download_media(self, file_id: str) -> dict | None:
                _ = file_id
                return None

        with (
            unittest.mock.patch(
                target="mugen.core.di.resolve_provider_class",
                return_value=DummyTelegramClientClass,
            ),
            self.assertNoLogs("root", level="ERROR"),
        ):
            di._build_provider(config, injector, provider_name="telegram_client")

        self.assertIsInstance(injector.telegram_client, DummyTelegramClientClass)
