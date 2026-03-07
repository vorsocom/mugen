"""Tests for live multi-profile platform runtime reload helpers."""

from __future__ import annotations

import copy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from mugen.core.di.injector import DependencyInjector
from mugen.core.service import platform_runtime_reload as reload_mod
from mugen.core.utility.platform_runtime_profile import build_config_namespace


def _current_config() -> dict:
    return {
        "mugen": {
            "platforms": ["line", "telegram"],
        },
        "line": {
            "webhook": {
                "path_token": "line-path-1",
            },
            "channel": {
                "secret": "line-secret-1",
            },
        },
        "telegram": {
            "bot": {
                "token": "telegram-token-1",
            },
            "webhook": {
                "path_token": "telegram-path-1",
                "secret_token": "telegram-secret-1",
            },
        },
    }


class _TelegramIPCExtension:
    platforms = ["telegram"]

    def __init__(self, config):
        self._config = config
        self._client = None
        self._event_dedup_ttl_seconds = 1

    def _resolve_event_dedup_ttl_seconds(self) -> int:
        return 86400


class TestMugenServicePlatformRuntimeReload(unittest.IsolatedAsyncioTestCase):
    """Covers runtime-profile reload coordination and rollback behavior."""

    async def test_private_helpers_cover_config_resolution_and_reference_refresh(
        self,
    ) -> None:
        current_config = build_config_namespace(_current_config())
        logger = Mock()
        injector = DependencyInjector(config=current_config, logging_gateway=logger)

        self.assertIs(reload_mod._logger_from_injector(injector), logger)  # pylint: disable=protected-access
        self.assertIsNone(
            reload_mod._logger_from_injector(  # pylint: disable=protected-access
                DependencyInjector(config=current_config)
            )
        )
        self.assertEqual(
            reload_mod._config_dict({"mugen": {"platforms": ["line"]}}),  # pylint: disable=protected-access
            {"mugen": {"platforms": ["line"]}},
        )
        self.assertEqual(
            reload_mod._config_dict(current_config)["mugen"]["platforms"],  # pylint: disable=protected-access
            ["line", "telegram"],
        )
        with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError):
            reload_mod._config_dict(None)  # pylint: disable=protected-access

        with patch.object(reload_mod.di, "_resolve_config_file", return_value="resolved.toml"):
            self.assertEqual(
                reload_mod._resolve_config_file(),  # pylint: disable=protected-access
                "resolved.toml",
            )
        self.assertEqual(
            reload_mod._resolve_config_file(" next.toml "),  # pylint: disable=protected-access
            "next.toml",
        )
        with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
            reload_mod._resolve_config_file("   ")  # pylint: disable=protected-access
        self.assertEqual(ex.exception.status_code, 400)

        self.assertEqual(
            reload_mod._active_platforms({"mugen": {"platforms": ["line"]}}),  # pylint: disable=protected-access
            ("line",),
        )
        self.assertEqual(
            reload_mod._active_platforms({"mugen": []}),  # pylint: disable=protected-access
            (),
        )
        self.assertFalse(
            reload_mod._profile_config_changed(  # pylint: disable=protected-access
                current_config,
                current_config,
                platform="line",
            )
        )
        self.assertEqual(
            reload_mod._unchanged_profile_diff(  # pylint: disable=protected-access
                current_config,
                platform="line",
            ),
            {
                "added": [],
                "removed": [],
                "updated": [],
                "unchanged": ["default"],
            },
        )

        refreshed_children: list[SimpleNamespace] = []

        class _ConfigAwareNode:
            platforms = ["telegram"]

            def __init__(self) -> None:
                self._config = None
                self._client = None
                self._event_dedup_ttl_seconds = 0
                self._typing_enabled = None
                self._ipc_extensions = [SimpleNamespace(_config=None)]

            def refresh_runtime_config(self, *, config):
                refreshed_children.append(config)

            def _resolve_event_dedup_ttl_seconds(self) -> int:
                return 86400

            def _resolve_typing_enabled(self) -> bool:
                return False

        node = _ConfigAwareNode()
        injector.telegram_client = SimpleNamespace(name="telegram-client")
        injector.ipc_service = node

        collections = list(reload_mod._iter_extension_collections(node))  # pylint: disable=protected-access
        self.assertEqual(len(collections), 1)

        reload_mod._refresh_runtime_config_references(  # pylint: disable=protected-access
            injector,
            config=current_config,
        )
        self.assertIs(node._config, current_config)
        self.assertIs(node._client, injector.telegram_client)
        self.assertEqual(node._event_dedup_ttl_seconds, 86400)
        self.assertFalse(node._typing_enabled)
        self.assertIs(node._ipc_extensions[0]._config, current_config)
        self.assertEqual(refreshed_children, [current_config])

        noisy_node = SimpleNamespace(
            _config=None,
            _event_dedup_ttl_seconds=0,
            _typing_enabled=True,
            _resolve_event_dedup_ttl_seconds=Mock(side_effect=RuntimeError("bad ttl")),
            _resolve_typing_enabled=Mock(side_effect=RuntimeError("bad typing")),
        )
        reload_mod._refresh_runtime_config_reference(  # pylint: disable=protected-access
            noisy_node,
            injector=injector,
            config=current_config,
            seen=set(),
        )
        self.assertIs(noisy_node._config, current_config)

        with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError):
            reload_mod._config_dict(  # pylint: disable=protected-access
                SimpleNamespace(dict=[])
            )

        skipped_node = SimpleNamespace(marker="unchanged")
        reload_mod._refresh_runtime_config_reference(  # pylint: disable=protected-access
            skipped_node,
            injector=injector,
            config=current_config,
            seen={id(skipped_node)},
        )
        self.assertEqual(skipped_node.marker, "unchanged")

        class _ExplodingNode:
            platforms = ["telegram"]

            def __init__(self) -> None:
                object.__setattr__(self, "_config", None)
                object.__setattr__(self, "_client", None)
                object.__setattr__(self, "_event_dedup_ttl_seconds", 0)
                object.__setattr__(self, "_typing_enabled", True)
                object.__setattr__(self, "_armed", True)

            def __setattr__(self, name, value) -> None:
                if getattr(self, "_armed", False) and name in {"_config", "_client"}:
                    raise RuntimeError(f"cannot set {name}")
                object.__setattr__(self, name, value)

        exploding_node = _ExplodingNode()
        reload_mod._refresh_runtime_config_reference(  # pylint: disable=protected-access
            exploding_node,
            injector=injector,
            config=current_config,
            seen=set(),
        )
        self.assertEqual(exploding_node._event_dedup_ttl_seconds, 0)
        self.assertTrue(exploding_node._typing_enabled)

        untyped_node = SimpleNamespace(
            platforms=["web"],
            _client="original",
            _event_dedup_ttl_seconds=0,
            _resolve_event_dedup_ttl_seconds="not-callable",
            _typing_enabled=True,
            _resolve_typing_enabled="not-callable",
        )
        reload_mod._refresh_runtime_config_reference(  # pylint: disable=protected-access
            untyped_node,
            injector=injector,
            config=current_config,
            seen=set(),
        )
        self.assertEqual(untyped_node._client, "original")
        self.assertEqual(untyped_node._event_dedup_ttl_seconds, 0)
        self.assertTrue(untyped_node._typing_enabled)

    async def test_reload_platform_runtime_profiles_updates_clients_and_extensions(
        self,
    ) -> None:
        current_dict = _current_config()
        next_dict = copy.deepcopy(current_dict)
        next_dict["telegram"] = {
            "profiles": [
                {
                    "key": "default",
                    "bot": {
                        "token": "telegram-token-2",
                    },
                    "webhook": {
                        "path_token": "telegram-path-2",
                        "secret_token": "telegram-secret-2",
                    },
                }
            ]
        }

        current_config = build_config_namespace(current_dict)
        logger = Mock()
        telegram_client = SimpleNamespace(
            reload_profiles=AsyncMock(
                return_value={
                    "added": [],
                    "removed": [],
                    "updated": ["default"],
                    "unchanged": [],
                }
            )
        )
        line_client = SimpleNamespace(reload_profiles=AsyncMock())
        extension = _TelegramIPCExtension(current_config)
        ipc_service = SimpleNamespace(
            _config=current_config,
            _ipc_extensions=[extension],
        )
        injector = DependencyInjector(
            config=current_config,
            logging_gateway=logger,
            ipc_service=ipc_service,
            line_client=line_client,
            telegram_client=telegram_client,
        )

        with (
            patch.object(reload_mod.di, "_load_config", return_value=next_dict),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            result = await reload_mod.reload_platform_runtime_profiles(
                injector=injector,
            )

        telegram_client.reload_profiles.assert_awaited_once()
        line_client.reload_profiles.assert_not_awaited()
        self.assertIs(injector.config, ipc_service._config)
        self.assertIs(injector.config, extension._config)
        self.assertIs(telegram_client, extension._client)
        self.assertEqual(extension._event_dedup_ttl_seconds, 86400)
        self.assertEqual(
            result["platforms"]["telegram"]["status"],
            "reloaded",
        )
        self.assertEqual(
            result["platforms"]["line"]["status"],
            "unchanged",
        )
        self.assertEqual(
            result["platforms"]["telegram"]["updated"],
            ["default"],
        )
        logger.info.assert_called_once()

    async def test_reload_platform_runtime_profiles_rejects_platform_activation_changes(
        self,
    ) -> None:
        current_dict = _current_config()
        next_dict = copy.deepcopy(current_dict)
        next_dict["mugen"]["platforms"] = ["line", "telegram", "wechat"]

        injector = DependencyInjector(
            config=build_config_namespace(current_dict),
            telegram_client=SimpleNamespace(reload_profiles=AsyncMock()),
            line_client=SimpleNamespace(reload_profiles=AsyncMock()),
        )

        with (
            patch.object(reload_mod.di, "_load_config", return_value=next_dict),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
                await reload_mod.reload_platform_runtime_profiles(injector=injector)

        self.assertEqual(ex.exception.status_code, 409)
        self.assertEqual(
            ex.exception.details["activation_changes"],
            ["wechat"],
        )

    async def test_reload_platform_runtime_profiles_rolls_back_prior_platforms_on_failure(
        self,
    ) -> None:
        current_dict = _current_config()
        next_dict = copy.deepcopy(current_dict)
        next_dict["line"]["channel"]["secret"] = "line-secret-2"
        next_dict["telegram"]["webhook"]["secret_token"] = "telegram-secret-2"

        current_config = build_config_namespace(current_dict)
        line_client = SimpleNamespace(
            reload_profiles=AsyncMock(
                side_effect=[
                    {
                        "added": [],
                        "removed": [],
                        "updated": ["default"],
                        "unchanged": [],
                    },
                    {
                        "added": [],
                        "removed": [],
                        "updated": ["default"],
                        "unchanged": [],
                    },
                ]
            )
        )
        telegram_client = SimpleNamespace(
            reload_profiles=AsyncMock(side_effect=RuntimeError("startup failed"))
        )
        injector = DependencyInjector(
            config=current_config,
            line_client=line_client,
            telegram_client=telegram_client,
        )

        with (
            patch.object(reload_mod.di, "_load_config", return_value=next_dict),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
                await reload_mod.reload_platform_runtime_profiles(injector=injector)

        self.assertIn("Live runtime profile reload failed", str(ex.exception))
        self.assertEqual(line_client.reload_profiles.await_count, 2)
        self.assertEqual(telegram_client.reload_profiles.await_count, 1)
        self.assertEqual(
            ex.exception.details["platform_results"]["line"]["rollback_status"],
            "restored",
        )

    async def test_reload_platform_runtime_profiles_requires_active_client_and_reload_hook(
        self,
    ) -> None:
        current_dict = _current_config()
        changed_line = copy.deepcopy(current_dict)
        changed_line["line"] = {
            "profiles": [
                {
                    "key": "default",
                    "webhook": {"path_token": "line-path-2"},
                    "channel": {"secret": "line-secret-2"},
                }
            ]
        }

        injector = DependencyInjector(config=build_config_namespace(current_dict))
        with (
            patch.object(reload_mod.di, "_load_config", return_value=changed_line),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
                await reload_mod.reload_platform_runtime_profiles(injector=injector)
        self.assertEqual(ex.exception.status_code, 500)
        self.assertIn("line", str(ex.exception))

        injector.line_client = SimpleNamespace(reload_profiles=None)
        injector.telegram_client = SimpleNamespace(
            reload_profiles=AsyncMock(
                return_value={
                    "added": [],
                    "removed": [],
                    "updated": [],
                    "unchanged": ["default"],
                }
            )
        )
        with (
            patch.object(reload_mod.di, "_load_config", return_value=changed_line),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
                await reload_mod.reload_platform_runtime_profiles(injector=injector)
        self.assertEqual(ex.exception.status_code, 500)
        self.assertIn("does not support live profile reload", str(ex.exception))

    async def test_reload_platform_runtime_profiles_preserves_error_details_and_rollback_failures(
        self,
    ) -> None:
        current_dict = _current_config()
        next_dict = copy.deepcopy(current_dict)
        next_dict["line"]["channel"]["secret"] = "line-secret-2"
        next_dict["telegram"]["webhook"]["secret_token"] = "telegram-secret-2"

        current_config = build_config_namespace(current_dict)
        line_client = SimpleNamespace(
            reload_profiles=AsyncMock(
                side_effect=[
                    {
                        "added": [],
                        "removed": [],
                        "updated": ["default"],
                        "unchanged": [],
                    },
                    RuntimeError("rollback failed"),
                ]
            )
        )
        telegram_client = SimpleNamespace(
            reload_profiles=AsyncMock(
                side_effect=reload_mod.PlatformRuntimeProfileReloadError(
                    "telegram reload rejected",
                    status_code=422,
                    details={"cause": "invalid token"},
                )
            )
        )
        injector = DependencyInjector(
            config=current_config,
            line_client=line_client,
            telegram_client=telegram_client,
        )

        with (
            patch.object(reload_mod.di, "_load_config", return_value=next_dict),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
                await reload_mod.reload_platform_runtime_profiles(
                    injector=injector,
                    config_file="custom.toml",
                )

        self.assertEqual(ex.exception.status_code, 422)
        self.assertEqual(ex.exception.details["cause"], "invalid token")
        self.assertIn("platform_results", ex.exception.details)
        self.assertEqual(
            ex.exception.details["rollback_failures"]["line"],
            "RuntimeError: rollback failed",
        )

    async def test_reload_platform_runtime_profiles_covers_invalid_injector_and_rollback_unavailable(
        self,
    ) -> None:
        with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
            await reload_mod.reload_platform_runtime_profiles(
                injector=SimpleNamespace()
            )
        self.assertEqual(ex.exception.status_code, 500)

        current_dict = _current_config()
        next_dict = copy.deepcopy(current_dict)
        next_dict["line"]["channel"]["secret"] = "line-secret-2"
        next_dict["telegram"]["webhook"]["secret_token"] = "telegram-secret-2"

        current_config = build_config_namespace(current_dict)
        line_client = SimpleNamespace(
            reload_profiles=AsyncMock(
                return_value={
                    "added": [],
                    "removed": [],
                    "updated": ["default"],
                    "unchanged": [],
                }
            )
        )

        async def _telegram_reload(_config):
            line_client.reload_profiles = None
            raise RuntimeError("telegram startup failed")

        injector = DependencyInjector(
            config=current_config,
            line_client=line_client,
            telegram_client=SimpleNamespace(
                reload_profiles=AsyncMock(side_effect=_telegram_reload)
            ),
        )

        with (
            patch.object(reload_mod.di, "_load_config", return_value=next_dict),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            with self.assertRaises(reload_mod.PlatformRuntimeProfileReloadError) as ex:
                await reload_mod.reload_platform_runtime_profiles(injector=injector)

        self.assertEqual(
            ex.exception.details["rollback_failures"]["line"],
            "rollback unavailable",
        )

    async def test_reload_platform_runtime_profiles_returns_without_logger(self) -> None:
        current_dict = _current_config()
        current_config = build_config_namespace(current_dict)
        injector = DependencyInjector(
            config=current_config,
            line_client=SimpleNamespace(reload_profiles=AsyncMock()),
            telegram_client=SimpleNamespace(reload_profiles=AsyncMock()),
        )

        with (
            patch.object(reload_mod.di, "_load_config", return_value=current_dict),
            patch.object(reload_mod.di, "_validate_core_module_schema"),
        ):
            result = await reload_mod.reload_platform_runtime_profiles(
                injector=injector,
            )

        self.assertEqual(
            result["platforms"]["line"]["status"],
            "unchanged",
        )
        self.assertEqual(
            result["platforms"]["telegram"]["status"],
            "unchanged",
        )
