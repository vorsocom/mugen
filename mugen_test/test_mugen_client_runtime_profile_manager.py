"""Unit tests for ACP-backed multi-profile client managers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from mugen.core.client import line as line_mod
from mugen.core.client import runtime_profile_manager as rpm_mod
from mugen.core.client import telegram as telegram_mod
from mugen.core.client import wechat as wechat_mod
from mugen.core.client import whatsapp as whatsapp_mod
from mugen.core.plugin.acp.service.messaging_client_profile import (
    RuntimeMessagingClientProfileSpec,
)
from mugen.core.utility.client_profile_runtime import client_profile_scope
from mugen.core.utility.messaging_client_user_access import (
    MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
    MessagingClientUserAccessPolicy,
)
from mugen.core.utility.platform_runtime_profile import build_config_namespace

_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000111")
_DEFAULT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_SECONDARY_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_TERTIARY_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _root_config() -> SimpleNamespace:
    return build_config_namespace({})


def _runtime_spec(
    platform: str,
    *,
    client_profile_id: uuid.UUID,
    profile_key: str,
    settings: dict | None = None,
) -> RuntimeMessagingClientProfileSpec:
    platform_settings = {
        "client_profile_id": str(client_profile_id),
        "client_profile_key": profile_key,
    }
    platform_settings.update(settings or {})
    return RuntimeMessagingClientProfileSpec(
        client_profile_id=client_profile_id,
        tenant_id=_TENANT_ID,
        platform_key=platform,
        profile_key=profile_key,
        config=build_config_namespace({platform: platform_settings}),
        snapshot={
            "id": str(client_profile_id),
            "profile_key": profile_key,
            "settings": settings or {},
        },
    )


class _MessagingClientProfileServiceStub:
    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def list_active_runtime_specs(
        self,
        *,
        config,
        platform_key: str,
    ) -> tuple[RuntimeMessagingClientProfileSpec, ...]:
        _ = config
        self.calls.append(platform_key)
        if not self._responses:
            return ()
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


class _LifecycleClient:
    instances: list["_LifecycleClient"] = []

    def __init__(self, config: SimpleNamespace = None, **_kwargs) -> None:
        platform = next(
            key
            for key in vars(config).keys()
            if not key.startswith("_") and key != "dict"
        )
        platform_cfg = getattr(config, platform)
        self.platform = platform
        self.client_profile_id = str(platform_cfg.client_profile_id)
        self.client_profile_key = str(platform_cfg.client_profile_key)
        self.verify_result = bool(getattr(platform_cfg, "verify_result", True))
        self.close_error = getattr(platform_cfg, "close_error", None)
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
        if isinstance(self.close_error, str) and self.close_error:
            raise RuntimeError(self.close_error)


class _DependencyCaptureClient:
    instances: list["_DependencyCaptureClient"] = []

    def __init__(
        self,
        config: SimpleNamespace = None,
        relational_storage_gateway=None,
        logging_gateway=None,
        messaging_service=None,
        **_kwargs,
    ) -> None:
        platform = next(
            key
            for key in vars(config).keys()
            if not key.startswith("_") and key != "dict"
        )
        platform_cfg = getattr(config, platform)
        self.client_profile_id = str(platform_cfg.client_profile_id)
        self.relational_storage_gateway = relational_storage_gateway
        self.logging_gateway = logging_gateway
        self.messaging_service = messaging_service
        _DependencyCaptureClient.instances.append(self)

    async def init(self) -> None:
        return None

    async def verify_startup(self) -> bool:
        return True

    async def close(self) -> None:
        return None


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
            key
            for key in vars(config).keys()
            if not key.startswith("_") and key != "dict"
        )
        platform_cfg = getattr(config, platform)
        self.client_profile_id = str(platform_cfg.client_profile_id)
        self.client_profile_key = str(platform_cfg.client_profile_key)
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
                "client_profile_id": self.client_profile_id,
                "client_profile_key": self.client_profile_key,
                "args": args,
                "kwargs": kwargs,
            }

        return _result


class _DelegationWhatsAppClientWithUserAccess(_DelegationClient):
    def user_access_policy(self) -> MessagingClientUserAccessPolicy:
        return MessagingClientUserAccessPolicy(
            mode=MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY,
            users=("15550077",),
            denied_message="Not enabled",
        )


class TestSimpleProfileClientManager(unittest.IsolatedAsyncioTestCase):
    """Covers lifecycle, routing, and reload branches for the shared manager."""

    def setUp(self) -> None:
        _LifecycleClient.instances.clear()
        _DependencyCaptureClient.instances.clear()

    async def test_manager_allows_zero_profiles_and_resolves_client_ids(self) -> None:
        empty_service = _MessagingClientProfileServiceStub(())
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=empty_service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await manager.init()
            self.assertEqual(manager.configured_client_profile_ids(), ())
            with self.assertRaisesRegex(RuntimeError, "No active client profiles"):
                manager._resolve_client_profile_id()  # pylint: disable=protected-access

        profiled_service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
                _runtime_spec(
                    "line",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                ),
            )
        )
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=profiled_service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await manager.init()
            self.assertEqual(
                manager.configured_client_profile_ids(),
                (str(_DEFAULT_ID), str(_SECONDARY_ID)),
            )
            with client_profile_scope(_SECONDARY_ID):
                self.assertEqual(
                    manager._resolve_client_profile_id(),  # pylint: disable=protected-access
                    str(_SECONDARY_ID),
                )
                self.assertEqual(
                    manager._client_for().client_profile_id,  # pylint: disable=protected-access
                    str(_SECONDARY_ID),
                )

            with self.assertRaisesRegex(RuntimeError, "Unknown client profile id"):
                manager._resolve_client_profile_id(  # pylint: disable=protected-access
                    uuid.UUID("00000000-0000-0000-0000-000000000099")
                )

        single_service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
            )
        )
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=single_service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await manager.init()
            self.assertEqual(
                manager._resolve_client_profile_id(),  # pylint: disable=protected-access
                str(_DEFAULT_ID),
            )

    async def test_manager_lifecycle_and_successful_reload(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
                _runtime_spec(
                    "line",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                ),
            ),
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    settings={"channel": {"secret": "updated"}},
                ),
                _runtime_spec(
                    "line",
                    client_profile_id=_TERTIARY_ID,
                    profile_key="tertiary",
                ),
            ),
        )
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )

            await manager.init()
            await manager.init()
            initial_clients = tuple(manager._clients.values())  # pylint: disable=protected-access

            self.assertTrue(manager._initialized)  # pylint: disable=protected-access
            self.assertTrue(await manager.verify_startup())
            self.assertEqual([client.init_count for client in initial_clients], [1, 1])

            diff = await manager.reload_profiles(_root_config())
            self.assertEqual(diff["added"], [str(_TERTIARY_ID)])
            self.assertEqual(diff["removed"], [str(_SECONDARY_ID)])
            self.assertEqual(diff["updated"], [str(_DEFAULT_ID)])
            self.assertEqual(diff["unchanged"], [])
            self.assertTrue(all(client.closed for client in initial_clients))

            await manager.close()
            self.assertEqual(manager._clients, {})  # pylint: disable=protected-access
            self.assertEqual(manager._profile_snapshots, {})  # pylint: disable=protected-access
            self.assertFalse(manager._initialized)  # pylint: disable=protected-access

    async def test_manager_forwards_shared_dependencies_to_profile_clients(
        self,
    ) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "whatsapp",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
            )
        )
        relational_storage_gateway = object()
        logging_gateway = object()
        messaging_service = object()

        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="whatsapp",
                client_cls=_DependencyCaptureClient,
                config=_root_config(),
                relational_storage_gateway=relational_storage_gateway,
                logging_gateway=logging_gateway,
                messaging_service=messaging_service,
            )
            await manager.init()

        self.assertEqual(len(_DependencyCaptureClient.instances), 1)
        client = _DependencyCaptureClient.instances[0]
        self.assertEqual(client.client_profile_id, str(_DEFAULT_ID))
        self.assertIs(
            client.relational_storage_gateway,
            relational_storage_gateway,
        )
        self.assertIs(client.logging_gateway, logging_gateway)
        self.assertIs(client.messaging_service, messaging_service)

    async def test_service_class_helper_and_manager_without_relational_gateway(
        self,
    ) -> None:
        imported_service_class = object()
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", None),
            patch.object(
                rpm_mod.importlib,
                "import_module",
                return_value=SimpleNamespace(
                    MessagingClientProfileService=imported_service_class
                ),
            ) as import_module,
        ):
            self.assertIs(
                rpm_mod._messaging_client_profile_service_class(),  # pylint: disable=protected-access
                imported_service_class,
            )
        import_module.assert_called_once_with(
            "mugen.core.plugin.acp.service.messaging_client_profile"
        )

        manager = rpm_mod.SimpleProfileClientManager(
            platform="line",
            client_cls=_LifecycleClient,
            config=_root_config(),
        )
        await manager.init()
        self.assertEqual(manager.configured_client_profile_ids(), ())
        self.assertTrue(await manager.verify_startup())
        await manager.close()

    async def test_manager_reload_failure_closes_candidate_clients(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
            ),
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    settings={"verify_result": False},
                ),
            ),
        )
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await manager.init()

            with self.assertRaisesRegex(RuntimeError, "startup probe failed"):
                await manager.reload_profiles(_root_config())

            self.assertTrue(_LifecycleClient.instances[-1].closed)

    async def test_manager_close_surfaces_profile_close_failures(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    settings={"close_error": "default close failed"},
                ),
                _runtime_spec(
                    "line",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                    settings={"close_error": "secondary close failed"},
                ),
            )
        )
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await manager.init()

            with self.assertRaisesRegex(
                RuntimeError,
                (
                    "line client profile cleanup failed: "
                    f"{_DEFAULT_ID}=RuntimeError: default close failed; "
                    f"{_SECONDARY_ID}=RuntimeError: secondary close failed"
                ),
            ):
                await manager.close()

            self.assertEqual(manager._clients, {})  # pylint: disable=protected-access
            self.assertFalse(manager._initialized)  # pylint: disable=protected-access

    async def test_manager_reload_failure_surfaces_candidate_cleanup_failure(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
            ),
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                    settings={
                        "verify_result": False,
                        "close_error": "candidate close failed",
                    },
                ),
            ),
        )
        with patch.object(
            rpm_mod,
            "MessagingClientProfileService",
            return_value=service,
        ):
            manager = rpm_mod.SimpleProfileClientManager(
                platform="line",
                client_cls=_LifecycleClient,
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            await manager.init()

            with self.assertRaisesRegex(
                RuntimeError,
                (
                    "line client profile reload failed after RuntimeError: "
                    "line client profile startup probe failed\\.; cleanup failed: "
                    "line client profile cleanup failed: "
                    f"{_DEFAULT_ID}=RuntimeError: candidate close failed"
                ),
            ):
                await manager.reload_profiles(_root_config())


class TestMultiProfilePlatformDelegates(unittest.IsolatedAsyncioTestCase):
    """Covers thin delegation wrappers for ACP-backed platform clients."""

    async def test_multi_profile_line_client_requires_scope_and_delegates(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "line",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
                _runtime_spec(
                    "line",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(line_mod, "DefaultLineClient", _DelegationClient),
        ):
            client = line_mod.MultiProfileLineClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with self.assertRaisesRegex(RuntimeError, "client_profile_id is required"):
                await client.reply_messages(
                    reply_token="reply-token",
                    messages=[{"type": "text"}],
                )

            with client_profile_scope(_SECONDARY_ID):
                result = await client.send_text_message(
                    recipient="U1",
                    text="hello",
                    reply_token="reply-token",
                )
                self.assertEqual(result["method"], "send_text_message")
                self.assertEqual(result["client_profile_id"], str(_SECONDARY_ID))

    async def test_multi_profile_telegram_client_delegates_to_selected_profile(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "telegram",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
                _runtime_spec(
                    "telegram",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(telegram_mod, "DefaultTelegramClient", _DelegationClient),
        ):
            client = telegram_mod.MultiProfileTelegramClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                result = await client.send_text_message(
                    chat_id="1",
                    text="hello",
                    reply_markup={"inline": True},
                    reply_to_message_id=1,
                )
                self.assertEqual(result["method"], "send_text_message")
                self.assertEqual(result["client_profile_id"], str(_SECONDARY_ID))

    async def test_multi_profile_wechat_client_delegates_to_selected_profile(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "wechat",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
                _runtime_spec(
                    "wechat",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(wechat_mod, "DefaultWeChatClient", _DelegationClient),
        ):
            client = wechat_mod.MultiProfileWeChatClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                result = await client.send_raw_message(payload={"msgtype": "text"})
                self.assertEqual(result["method"], "send_raw_message")
                self.assertEqual(result["client_profile_id"], str(_SECONDARY_ID))

    async def test_multi_profile_whatsapp_client_delegates_to_selected_profile(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "whatsapp",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
                _runtime_spec(
                    "whatsapp",
                    client_profile_id=_SECONDARY_ID,
                    profile_key="secondary",
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(whatsapp_mod, "DefaultWhatsAppClient", _DelegationClient),
        ):
            client = whatsapp_mod.MultiProfileWhatsAppClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                result = await client.send_text_message(
                    "hello",
                    "15550001",
                    "reply-1",
                )
                self.assertEqual(result["method"], "send_text_message")
                self.assertEqual(result["client_profile_id"], str(_SECONDARY_ID))

    async def test_multi_profile_whatsapp_client_user_access_policy_paths(self) -> None:
        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "whatsapp",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(
                whatsapp_mod,
                "DefaultWhatsAppClient",
                _DelegationWhatsAppClientWithUserAccess,
            ),
        ):
            client = whatsapp_mod.MultiProfileWhatsAppClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            policy = await client.user_access_policy()
            self.assertEqual(policy.mode, MESSAGING_CLIENT_USER_ACCESS_MODE_ALLOW_ONLY)
            self.assertEqual(policy.users, ("15550077",))
            self.assertEqual(policy.denied_message, "Not enabled")

        service = _MessagingClientProfileServiceStub(
            (
                _runtime_spec(
                    "whatsapp",
                    client_profile_id=_DEFAULT_ID,
                    profile_key="default",
                ),
            )
        )
        with (
            patch.object(rpm_mod, "MessagingClientProfileService", return_value=service),
            patch.object(whatsapp_mod, "DefaultWhatsAppClient", _DelegationClient),
        ):
            client = whatsapp_mod.MultiProfileWhatsAppClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            policy = await client.user_access_policy()
            self.assertEqual(policy, MessagingClientUserAccessPolicy())

    async def test_platform_delegate_wrappers_cover_remaining_methods(self) -> None:
        with (
            patch.object(
                rpm_mod,
                "MessagingClientProfileService",
                return_value=_MessagingClientProfileServiceStub(
                    (
                        _runtime_spec(
                            "line",
                            client_profile_id=_DEFAULT_ID,
                            profile_key="default",
                        ),
                        _runtime_spec(
                            "line",
                            client_profile_id=_SECONDARY_ID,
                            profile_key="secondary",
                        ),
                    )
                ),
            ),
            patch.object(line_mod, "DefaultLineClient", _DelegationClient),
        ):
            client = line_mod.MultiProfileLineClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                line_results = [
                    await client.push_messages(to="U1", messages=[{"type": "text"}]),
                    await client.multicast_messages(
                        to=["U1", "U2"],
                        messages=[{"type": "text"}],
                    ),
                    await client.send_image_message(
                        recipient="U1",
                        image={"url": "https://example.com/image.png"},
                    ),
                    await client.send_audio_message(
                        recipient="U1",
                        audio={"url": "https://example.com/audio.mp3"},
                    ),
                    await client.send_video_message(
                        recipient="U1",
                        video={"url": "https://example.com/video.mp4"},
                    ),
                    await client.send_file_message(
                        recipient="U1",
                        file={"url": "https://example.com/file.pdf"},
                    ),
                    await client.send_raw_message(
                        op="broadcast",
                        payload={"messages": [{"type": "text"}]},
                    ),
                    await client.download_media(message_id="m-1"),
                    await client.get_profile(user_id="U1"),
                    await client.emit_processing_signal(
                        "U1",
                        state="typing",
                        message_id="m-1",
                    ),
                ]
        self.assertEqual(
            [result["method"] for result in line_results],
            [
                "push_messages",
                "multicast_messages",
                "send_image_message",
                "send_audio_message",
                "send_video_message",
                "send_file_message",
                "send_raw_message",
                "download_media",
                "get_profile",
                "emit_processing_signal",
            ],
        )
        self.assertTrue(
            all(result["client_profile_id"] == str(_SECONDARY_ID) for result in line_results)
        )

        with (
            patch.object(
                rpm_mod,
                "MessagingClientProfileService",
                return_value=_MessagingClientProfileServiceStub(
                    (
                        _runtime_spec(
                            "telegram",
                            client_profile_id=_DEFAULT_ID,
                            profile_key="default",
                        ),
                        _runtime_spec(
                            "telegram",
                            client_profile_id=_SECONDARY_ID,
                            profile_key="secondary",
                        ),
                    )
                ),
            ),
            patch.object(telegram_mod, "DefaultTelegramClient", _DelegationClient),
        ):
            client = telegram_mod.MultiProfileTelegramClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                telegram_results = [
                    await client.send_audio_message(chat_id="1", audio={"id": "a-1"}),
                    await client.send_file_message(
                        chat_id="1",
                        document={"id": "d-1"},
                    ),
                    await client.send_image_message(chat_id="1", photo={"id": "p-1"}),
                    await client.send_video_message(chat_id="1", video={"id": "v-1"}),
                    await client.answer_callback_query(
                        callback_query_id="cb-1",
                        text="ok",
                        show_alert=True,
                    ),
                    await client.emit_processing_signal(
                        "1",
                        state="typing",
                        message_id="m-1",
                    ),
                    await client.download_media("file-1"),
                ]
        self.assertEqual(
            [result["method"] for result in telegram_results],
            [
                "send_audio_message",
                "send_file_message",
                "send_image_message",
                "send_video_message",
                "answer_callback_query",
                "emit_processing_signal",
                "download_media",
            ],
        )
        self.assertTrue(
            all(
                result["client_profile_id"] == str(_SECONDARY_ID)
                for result in telegram_results
            )
        )

        with (
            patch.object(
                rpm_mod,
                "MessagingClientProfileService",
                return_value=_MessagingClientProfileServiceStub(
                    (
                        _runtime_spec(
                            "wechat",
                            client_profile_id=_DEFAULT_ID,
                            profile_key="default",
                        ),
                        _runtime_spec(
                            "wechat",
                            client_profile_id=_SECONDARY_ID,
                            profile_key="secondary",
                        ),
                    )
                ),
            ),
            patch.object(wechat_mod, "DefaultWeChatClient", _DelegationClient),
        ):
            client = wechat_mod.MultiProfileWeChatClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                wechat_results = [
                    await client.send_text_message(recipient="U1", text="hello"),
                    await client.send_audio_message(recipient="U1", audio={"id": "a-1"}),
                    await client.send_file_message(recipient="U1", file={"id": "f-1"}),
                    await client.send_image_message(recipient="U1", image={"id": "i-1"}),
                    await client.send_video_message(recipient="U1", video={"id": "v-1"}),
                    await client.upload_media(
                        file_path="/tmp/example.bin",
                        media_type="image",
                    ),
                    await client.download_media(
                        media_id="media-1",
                        mime_type="image/png",
                    ),
                    await client.emit_processing_signal(
                        "U1",
                        state="typing",
                        message_id="m-1",
                    ),
                ]
        self.assertEqual(
            [result["method"] for result in wechat_results],
            [
                "send_text_message",
                "send_audio_message",
                "send_file_message",
                "send_image_message",
                "send_video_message",
                "upload_media",
                "download_media",
                "emit_processing_signal",
            ],
        )
        self.assertTrue(
            all(result["client_profile_id"] == str(_SECONDARY_ID) for result in wechat_results)
        )

        with (
            patch.object(
                rpm_mod,
                "MessagingClientProfileService",
                return_value=_MessagingClientProfileServiceStub(
                    (
                        _runtime_spec(
                            "whatsapp",
                            client_profile_id=_DEFAULT_ID,
                            profile_key="default",
                        ),
                        _runtime_spec(
                            "whatsapp",
                            client_profile_id=_SECONDARY_ID,
                            profile_key="secondary",
                        ),
                    )
                ),
            ),
            patch.object(whatsapp_mod, "DefaultWhatsAppClient", _DelegationClient),
        ):
            client = whatsapp_mod.MultiProfileWhatsAppClient(
                config=_root_config(),
                relational_storage_gateway=object(),
            )
            with client_profile_scope(_SECONDARY_ID):
                whatsapp_results = [
                    await client.delete_media("media-1"),
                    await client.download_media("https://example.com/media", "image/png"),
                    await client.retrieve_media_url("media-1"),
                    await client.send_audio_message({"id": "a-1"}, "15550001"),
                    await client.send_contacts_message({"name": "Alice"}, "15550001"),
                    await client.send_document_message({"id": "d-1"}, "15550001"),
                    await client.send_image_message({"id": "i-1"}, "15550001"),
                    await client.send_interactive_message({"type": "button"}, "15550001"),
                    await client.send_location_message({"lat": 1.0}, "15550001"),
                    await client.send_reaction_message({"emoji": "👍"}, "15550001"),
                    await client.send_sticker_message({"id": "s-1"}, "15550001"),
                    await client.send_template_message({"name": "tmpl"}, "15550001"),
                    await client.send_video_message({"id": "v-1"}, "15550001"),
                    await client.emit_processing_signal(
                        "15550001",
                        state="typing",
                        message_id="m-1",
                    ),
                    await client.upload_media("/tmp/example.bin", "image/png"),
                ]
        self.assertEqual(
            [result["method"] for result in whatsapp_results],
            [
                "delete_media",
                "download_media",
                "retrieve_media_url",
                "send_audio_message",
                "send_contacts_message",
                "send_document_message",
                "send_image_message",
                "send_interactive_message",
                "send_location_message",
                "send_reaction_message",
                "send_sticker_message",
                "send_template_message",
                "send_video_message",
                "emit_processing_signal",
                "upload_media",
            ],
        )
        self.assertTrue(
            all(
                result["client_profile_id"] == str(_SECONDARY_ID)
                for result in whatsapp_results
            )
        )
