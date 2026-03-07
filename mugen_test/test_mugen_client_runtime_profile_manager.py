"""Unit tests for runtime profile client managers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from mugen.core.client import line as line_mod
from mugen.core.client import runtime_profile_manager as rpm_mod
from mugen.core.client import telegram as telegram_mod
from mugen.core.client import wechat as wechat_mod
from mugen.core.client import whatsapp as whatsapp_mod
from mugen.core.utility.platform_runtime_profile import (
    build_config_namespace,
    runtime_profile_scope,
)


def _profiled_config(platform: str, keys: tuple[str, ...]) -> SimpleNamespace:
    return build_config_namespace(
        {
            platform: {
                "profiles": [{"key": key} for key in keys],
            }
        }
    )


class _LifecycleClient:
    instances: list["_LifecycleClient"] = []

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        platform = next(
            key for key in vars(config).keys() if not key.startswith("_") and key != "dict"
        )
        platform_cfg = getattr(config, platform)
        self.platform = platform
        self.runtime_profile_key = getattr(platform_cfg, "runtime_profile_key", None)
        self.verify_result = bool(getattr(platform_cfg, "verify_result", True))
        self.init_count = 0
        self.close_count = 0
        self.closed = False
        _LifecycleClient.instances.append(self)

    async def init(self) -> None:
        self.init_count += 1

    async def verify_startup(self) -> bool:
        return self.verify_result

    async def close(self) -> None:
        self.close_count += 1
        self.closed = True


class _DelegationClient:
    _method_names = (
        "answer_callback_query",
        "delete_media",
        "download_media",
        "emit_processing_signal",
        "get_profile",
        "multicast_messages",
        "push_messages",
        "reply_messages",
        "retrieve_media_url",
        "send_audio_message",
        "send_contacts_message",
        "send_document_message",
        "send_file_message",
        "send_image_message",
        "send_interactive_message",
        "send_location_message",
        "send_raw_message",
        "send_reaction_message",
        "send_sticker_message",
        "send_template_message",
        "send_text_message",
        "send_video_message",
        "upload_media",
    )

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        platform = next(
            key for key in vars(config).keys() if not key.startswith("_") and key != "dict"
        )
        platform_cfg = getattr(config, platform)
        self.runtime_profile_key = getattr(platform_cfg, "runtime_profile_key")
        self.init = AsyncMock()
        self.verify_startup = AsyncMock(return_value=True)
        self.close = AsyncMock()
        for method_name in self._method_names:
            setattr(
                self,
                method_name,
                AsyncMock(side_effect=self._make_result(method_name)),
            )

    def _make_result(self, method_name: str):
        async def _result(*args, **kwargs):
            return {
                "method": method_name,
                "runtime_profile_key": self.runtime_profile_key,
                "args": args,
                "kwargs": kwargs,
            }

        return _result


class TestSimpleProfileClientManager(unittest.IsolatedAsyncioTestCase):
    """Covers lifecycle, routing, and reload branches for the shared manager."""

    def setUp(self) -> None:
        _LifecycleClient.instances.clear()

    async def test_manager_requires_profiles_and_resolves_runtime_keys(self) -> None:
        with self.assertRaises(RuntimeError):
            rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=build_config_namespace({}),
            )

        manager = rpm_mod.SimpleProfileClientManager(
            platform="line",
            client_cls=_LifecycleClient,
            config=_profiled_config("line", ("default", "secondary")),
        )
        self.assertEqual(
            manager.configured_runtime_profile_keys(),
            ("default", "secondary"),
        )
        self.assertEqual(
            manager._resolve_runtime_profile_key(),  # pylint: disable=protected-access
            "default",
        )
        with runtime_profile_scope("secondary"):
            self.assertEqual(
                manager._resolve_runtime_profile_key(),  # pylint: disable=protected-access
                "secondary",
            )
            self.assertEqual(
                manager._client_for().runtime_profile_key,  # pylint: disable=protected-access
                "secondary",
            )
        with self.assertRaises(RuntimeError):
            manager._resolve_runtime_profile_key("missing")  # pylint: disable=protected-access

        sole_manager = rpm_mod.SimpleProfileClientManager(
            platform="line",
            client_cls=_LifecycleClient,
            config=_profiled_config("line", ("custom",)),
        )
        self.assertEqual(
            sole_manager._resolve_runtime_profile_key(),  # pylint: disable=protected-access
            "custom",
        )

        no_default_manager = rpm_mod.SimpleProfileClientManager(
            platform="line",
            client_cls=_LifecycleClient,
            config=_profiled_config("line", ("alpha", "beta")),
        )
        with self.assertRaises(RuntimeError):
            no_default_manager._resolve_runtime_profile_key()  # pylint: disable=protected-access

    async def test_manager_lifecycle_and_successful_reload(self) -> None:
        manager = rpm_mod.SimpleProfileClientManager(
            platform="line",
            client_cls=_LifecycleClient,
            config=_profiled_config("line", ("default", "secondary")),
        )
        initial_clients = tuple(manager._clients.values())  # pylint: disable=protected-access

        await manager.init()
        await manager.init()
        self.assertTrue(manager._initialized)  # pylint: disable=protected-access
        self.assertTrue(await manager.verify_startup())
        self.assertEqual([client.init_count for client in initial_clients], [1, 1])

        next_config = build_config_namespace(
            {
                "line": {
                    "profiles": [
                        {"key": "default", "channel": {"secret": "updated"}},
                        {"key": "tertiary"},
                    ]
                }
            }
        )
        diff = await manager.reload_profiles(next_config)
        self.assertEqual(diff["added"], ["tertiary"])
        self.assertEqual(diff["removed"], ["secondary"])
        self.assertEqual(diff["updated"], ["default"])
        self.assertEqual(diff["unchanged"], [])
        self.assertTrue(all(client.closed for client in initial_clients))

        await manager.close()
        self.assertEqual(manager._clients, {})  # pylint: disable=protected-access
        self.assertEqual(manager._profile_snapshots, {})  # pylint: disable=protected-access
        self.assertFalse(manager._initialized)  # pylint: disable=protected-access

    async def test_manager_reload_failure_closes_candidate_clients(self) -> None:
        manager = rpm_mod.SimpleProfileClientManager(
            platform="line",
            client_cls=_LifecycleClient,
            config=_profiled_config("line", ("default",)),
        )
        next_config = build_config_namespace(
            {
                "line": {
                    "profiles": [
                        {"key": "default", "verify_result": False},
                    ]
                }
            }
        )

        with self.assertRaises(RuntimeError):
            await manager.reload_profiles(next_config)

        self.assertEqual(
            [client.closed for client in _LifecycleClient.instances[-1:]],
            [True],
        )


class TestMultiProfilePlatformDelegates(unittest.IsolatedAsyncioTestCase):
    """Covers the thin delegation wrappers for multi-profile platform clients."""

    async def test_multi_profile_line_client_delegates_to_selected_profile(self) -> None:
        with patch.object(line_mod, "DefaultLineClient", _DelegationClient):
            client = line_mod.MultiProfileLineClient(
                config=_profiled_config("line", ("default", "secondary"))
            )
            default_result = await client.reply_messages(
                reply_token="reply-token",
                messages=[{"type": "text"}],
            )
            self.assertEqual(default_result["runtime_profile_key"], "default")

            with runtime_profile_scope("secondary"):
                calls = [
                    (
                        client.push_messages,
                        {"to": "U1", "messages": [{"type": "text"}]},
                        "push_messages",
                    ),
                    (
                        client.multicast_messages,
                        {"to": ["U1", "U2"], "messages": [{"type": "text"}]},
                        "multicast_messages",
                    ),
                    (
                        client.send_text_message,
                        {
                            "recipient": "U1",
                            "text": "hello",
                            "reply_token": "reply-token",
                        },
                        "send_text_message",
                    ),
                    (
                        client.send_image_message,
                        {
                            "recipient": "U1",
                            "image": {"uri": "mxc://image"},
                            "reply_token": None,
                        },
                        "send_image_message",
                    ),
                    (
                        client.send_audio_message,
                        {
                            "recipient": "U1",
                            "audio": {"uri": "mxc://audio"},
                            "reply_token": None,
                        },
                        "send_audio_message",
                    ),
                    (
                        client.send_video_message,
                        {
                            "recipient": "U1",
                            "video": {"uri": "mxc://video"},
                            "reply_token": None,
                        },
                        "send_video_message",
                    ),
                    (
                        client.send_file_message,
                        {
                            "recipient": "U1",
                            "file": {"uri": "mxc://file"},
                            "reply_token": None,
                        },
                        "send_file_message",
                    ),
                    (
                        client.send_raw_message,
                        {"op": "push", "payload": {"x": 1}},
                        "send_raw_message",
                    ),
                    (
                        client.download_media,
                        {"message_id": "msg-1"},
                        "download_media",
                    ),
                    (
                        client.get_profile,
                        {"user_id": "U1"},
                        "get_profile",
                    ),
                ]
                for method, kwargs, expected_method in calls:
                    result = await method(**kwargs)
                    self.assertEqual(result["method"], expected_method)
                    self.assertEqual(result["runtime_profile_key"], "secondary")

                emit_result = await client.emit_processing_signal(
                    "U1",
                    state="start",
                    message_id="m1",
                )
                self.assertEqual(emit_result["method"], "emit_processing_signal")
                self.assertEqual(
                    emit_result["runtime_profile_key"],
                    "secondary",
                )

    async def test_multi_profile_telegram_client_delegates_to_selected_profile(self) -> None:
        with patch.object(telegram_mod, "DefaultTelegramClient", _DelegationClient):
            client = telegram_mod.MultiProfileTelegramClient(
                config=_profiled_config("telegram", ("default", "secondary"))
            )

            with runtime_profile_scope("secondary"):
                calls = [
                    (
                        client.send_text_message,
                        {
                            "chat_id": "1",
                            "text": "hello",
                            "reply_markup": {"inline": True},
                            "reply_to_message_id": 1,
                        },
                        "send_text_message",
                    ),
                    (
                        client.send_audio_message,
                        {
                            "chat_id": "1",
                            "audio": {"file_id": "audio"},
                            "reply_to_message_id": 2,
                        },
                        "send_audio_message",
                    ),
                    (
                        client.send_file_message,
                        {
                            "chat_id": "1",
                            "document": {"file_id": "doc"},
                            "reply_to_message_id": 3,
                        },
                        "send_file_message",
                    ),
                    (
                        client.send_image_message,
                        {
                            "chat_id": "1",
                            "photo": {"file_id": "photo"},
                            "reply_to_message_id": 4,
                        },
                        "send_image_message",
                    ),
                    (
                        client.send_video_message,
                        {
                            "chat_id": "1",
                            "video": {"file_id": "video"},
                            "reply_to_message_id": 5,
                        },
                        "send_video_message",
                    ),
                    (
                        client.answer_callback_query,
                        {
                            "callback_query_id": "cq-1",
                            "text": "ok",
                            "show_alert": True,
                        },
                        "answer_callback_query",
                    ),
                ]
                for method, kwargs, expected_method in calls:
                    result = await method(**kwargs)
                    self.assertEqual(result["method"], expected_method)
                    self.assertEqual(result["runtime_profile_key"], "secondary")

                emit_result = await client.emit_processing_signal(
                    "1",
                    state="start",
                    message_id="m1",
                )
                self.assertEqual(emit_result["method"], "emit_processing_signal")

                download_result = await client.download_media("file-1")
                self.assertEqual(download_result["method"], "download_media")

    async def test_multi_profile_wechat_client_delegates_to_selected_profile(self) -> None:
        with patch.object(wechat_mod, "DefaultWeChatClient", _DelegationClient):
            client = wechat_mod.MultiProfileWeChatClient(
                config=_profiled_config("wechat", ("default", "secondary"))
            )

            with runtime_profile_scope("secondary"):
                calls = [
                    (
                        client.send_text_message,
                        {
                            "recipient": "user-1",
                            "text": "hello",
                            "reply_to": "ref-1",
                        },
                        "send_text_message",
                    ),
                    (
                        client.send_audio_message,
                        {
                            "recipient": "user-1",
                            "audio": {"media_id": "audio"},
                            "reply_to": None,
                        },
                        "send_audio_message",
                    ),
                    (
                        client.send_file_message,
                        {
                            "recipient": "user-1",
                            "file": {"media_id": "file"},
                            "reply_to": None,
                        },
                        "send_file_message",
                    ),
                    (
                        client.send_image_message,
                        {
                            "recipient": "user-1",
                            "image": {"media_id": "image"},
                            "reply_to": None,
                        },
                        "send_image_message",
                    ),
                    (
                        client.send_video_message,
                        {
                            "recipient": "user-1",
                            "video": {"media_id": "video"},
                            "reply_to": None,
                        },
                        "send_video_message",
                    ),
                    (
                        client.send_raw_message,
                        {"payload": {"msgtype": "text"}},
                        "send_raw_message",
                    ),
                    (
                        client.upload_media,
                        {"file_path": "/tmp/file", "media_type": "image"},
                        "upload_media",
                    ),
                    (
                        client.download_media,
                        {"media_id": "media-1", "mime_type": "image/png"},
                        "download_media",
                    ),
                ]
                for method, kwargs, expected_method in calls:
                    result = await method(**kwargs)
                    self.assertEqual(result["method"], expected_method)
                    self.assertEqual(result["runtime_profile_key"], "secondary")

                emit_result = await client.emit_processing_signal(
                    "user-1",
                    state="start",
                    message_id="m1",
                )
                self.assertEqual(emit_result["method"], "emit_processing_signal")

    async def test_multi_profile_whatsapp_client_delegates_to_selected_profile(self) -> None:
        with patch.object(whatsapp_mod, "DefaultWhatsAppClient", _DelegationClient):
            client = whatsapp_mod.MultiProfileWhatsAppClient(
                config=_profiled_config("whatsapp", ("default", "secondary"))
            )

            with runtime_profile_scope("secondary"):
                calls = [
                    (client.delete_media, ("media-1",), {}, "delete_media"),
                    (
                        client.download_media,
                        ("https://example/media", "image/png"),
                        {},
                        "download_media",
                    ),
                    (
                        client.retrieve_media_url,
                        ("media-1",),
                        {},
                        "retrieve_media_url",
                    ),
                    (
                        client.send_audio_message,
                        ({"id": "audio"}, "15550001", "reply-1"),
                        {},
                        "send_audio_message",
                    ),
                    (
                        client.send_contacts_message,
                        ({"contacts": []}, "15550001", "reply-1"),
                        {},
                        "send_contacts_message",
                    ),
                    (
                        client.send_document_message,
                        ({"id": "doc"}, "15550001", "reply-1"),
                        {},
                        "send_document_message",
                    ),
                    (
                        client.send_image_message,
                        ({"id": "img"}, "15550001", "reply-1"),
                        {},
                        "send_image_message",
                    ),
                    (
                        client.send_interactive_message,
                        ({"type": "button"}, "15550001", "reply-1"),
                        {},
                        "send_interactive_message",
                    ),
                    (
                        client.send_location_message,
                        ({"lat": 1}, "15550001", "reply-1"),
                        {},
                        "send_location_message",
                    ),
                    (
                        client.send_reaction_message,
                        ({"emoji": "👍"}, "15550001"),
                        {},
                        "send_reaction_message",
                    ),
                    (
                        client.send_sticker_message,
                        ({"id": "sticker"}, "15550001", "reply-1"),
                        {},
                        "send_sticker_message",
                    ),
                    (
                        client.send_template_message,
                        ({"name": "template"}, "15550001", "reply-1"),
                        {},
                        "send_template_message",
                    ),
                    (
                        client.send_text_message,
                        ("hello", "15550001", "reply-1"),
                        {},
                        "send_text_message",
                    ),
                    (
                        client.send_video_message,
                        ({"id": "video"}, "15550001", "reply-1"),
                        {},
                        "send_video_message",
                    ),
                    (
                        client.upload_media,
                        ("/tmp/file", "image/png"),
                        {},
                        "upload_media",
                    ),
                ]
                for method, args, kwargs, expected_method in calls:
                    result = await method(*args, **kwargs)
                    self.assertEqual(result["method"], expected_method)
                    self.assertEqual(result["runtime_profile_key"], "secondary")

                emit_result = await client.emit_processing_signal(
                    "15550001",
                    state="start",
                    message_id="m1",
                )
                self.assertEqual(emit_result["method"], "emit_processing_signal")
