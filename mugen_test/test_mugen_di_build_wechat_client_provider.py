"""Provides unit tests for mugen.core.di._build_wechat_client_provider."""

import unittest
import unittest.mock

from mugen.core import di
from mugen.core.contract.client.wechat import IWeChatClient


# pylint: disable=protected-access
class TestDIBuildWeChatClient(unittest.TestCase):
    """Unit tests for mugen.core.di._build_provider (wechat_client)."""

    def test_incorrectly_typed_injector(self) -> None:
        config = {
            "mugen": {
                "platforms": ["wechat"],
                "modules": {
                    "core": {
                        "client": {
                            "wechat": "default",
                        }
                    }
                },
            }
        }

        with self.assertLogs("root", level="ERROR") as logger:
            di._build_provider(config, None, provider_name="wechat_client")

        self.assertEqual(
            logger.output[0],
            "ERROR:root:Invalid injector (wechat_client).",
        )

    def test_platform_inactive(self) -> None:
        config = {
            "mugen": {
                "platforms": [],
            }
        }
        injector = di.injector.DependencyInjector()

        with self.assertLogs("root", level="WARNING") as logger:
            di._build_provider(config, injector, provider_name="wechat_client")

        self.assertEqual(
            logger.output[1],
            "WARNING:root:WeChat platform not active. Client not loaded.",
        )

    def test_module_configuration_unavailable(self) -> None:
        config = {
            "mugen": {
                "platforms": ["wechat"],
            }
        }
        injector = di.injector.DependencyInjector()

        with self.assertLogs("root", level="ERROR") as logger:
            di._build_provider(config, injector, provider_name="wechat_client")

        self.assertEqual(
            logger.output[0],
            "ERROR:root:Invalid configuration (wechat_client).",
        )

    def test_normal_execution(self) -> None:
        config = {
            "mugen": {
                "platforms": ["wechat"],
                "modules": {
                    "core": {
                        "client": {
                            "wechat": "default",
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

        class DummyWeChatClientClass(IWeChatClient):
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
                return None

            async def verify_startup(self) -> bool:
                return True

            async def close(self) -> None:
                return None

            async def send_text_message(
                self,
                *,
                recipient: str,
                text: str,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, text, reply_to)
                return None

            async def send_audio_message(
                self,
                *,
                recipient: str,
                audio: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, audio, reply_to)
                return None

            async def send_file_message(
                self,
                *,
                recipient: str,
                file: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, file, reply_to)
                return None

            async def send_image_message(
                self,
                *,
                recipient: str,
                image: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, image, reply_to)
                return None

            async def send_video_message(
                self,
                *,
                recipient: str,
                video: dict,
                reply_to: str | None = None,
            ) -> dict | None:
                _ = (recipient, video, reply_to)
                return None

            async def send_raw_message(self, *, payload: dict) -> dict | None:
                _ = payload
                return None

            async def upload_media(
                self,
                *,
                file_path: str,
                media_type: str,
            ) -> dict | None:
                _ = (file_path, media_type)
                return None

            async def download_media(
                self,
                *,
                media_id: str,
                mime_type: str | None = None,
            ) -> dict | None:
                _ = (media_id, mime_type)
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

        with (
            unittest.mock.patch(
                target="mugen.core.di.resolve_provider_class",
                return_value=DummyWeChatClientClass,
            ),
            self.assertNoLogs("root", level="ERROR"),
        ):
            di._build_provider(config, injector, provider_name="wechat_client")

        self.assertIsInstance(injector.wechat_client, DummyWeChatClientClass)

