"""Unit tests for mugen.core.utility.platform_runtime_profile."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mugen.core.utility import platform_runtime_profile as profile_mod


class TestMuGenPlatformRuntimeProfile(unittest.TestCase):
    """Covers profile normalization, lookup, and task-local scoping helpers."""

    def _config(self) -> dict:
        return {
            "basedir": "/tmp/mugen",
            "line": {
                "api": {"base_url": "https://line.test"},
                "profiles": [
                    {
                        "key": "default",
                        "webhook": {"path_token": "line-default"},
                        "channel": {"secret": "secret-1"},
                    },
                    {
                        "key": "secondary",
                        "webhook": {"path_token": "line-secondary"},
                        "channel": {"secret": "secret-2"},
                    },
                ],
            },
            "matrix": {
                "profiles": [
                    {
                        "key": "default",
                        "client": {"user": "@bot-default:test"},
                    },
                    {
                        "key": "secondary",
                        "client": {"user": "@bot-secondary:test"},
                    },
                ],
            },
            "wechat": {
                "profiles": [
                    {
                        "key": "default",
                        "provider": "official_account",
                        "webhook": {"path_token": "wechat-default"},
                    },
                    {
                        "key": "secondary",
                        "provider": "wecom",
                        "webhook": {"path_token": "wechat-secondary"},
                    },
                ],
            },
            "telegram": {
                "profiles": [
                    {
                        "key": "default",
                        "webhook": {
                            "path_token": "telegram-default",
                            "secret_token": "secret-default",
                        },
                    }
                ]
            },
            "signal": {
                "profiles": [
                    {
                        "key": "default",
                        "account": {"number": "+15550001"},
                    }
                ]
            },
            "whatsapp": {
                "profiles": [
                    {
                        "key": "default",
                        "business": {"phone_number_id": "12345"},
                    }
                ]
            },
        }

    def test_build_config_namespace_requires_mapping_and_namespace_result(self) -> None:
        with self.assertRaises(TypeError):
            profile_mod.build_config_namespace([])  # type: ignore[arg-type]

        with patch.object(profile_mod, "to_namespace", return_value=[]):
            with self.assertRaises(TypeError):
                profile_mod.build_config_namespace({"line": {}})

    def test_get_platform_profile_sections_and_clone_config(self) -> None:
        config = profile_mod.build_config_namespace(self._config())

        sections = profile_mod.get_platform_profile_sections(config, platform="line")
        self.assertEqual([section.key for section in sections], ["default", "secondary"])
        self.assertEqual(sections[0].api.base_url, "https://line.test")
        self.assertEqual(sections[1].channel.secret, "secret-2")
        self.assertEqual(sections[1].runtime_profile_key, "secondary")

        section = profile_mod.get_platform_profile_section(
            config,
            platform="line",
            runtime_profile_key="secondary",
        )
        self.assertEqual(section.webhook.path_token, "line-secondary")
        self.assertEqual(
            profile_mod.get_platform_profile_dicts(config, platform="line")[0]["key"],
            "default",
        )
        self.assertEqual(
            profile_mod.get_platform_runtime_profile_keys(config, platform="line"),
            ("default", "secondary"),
        )

        cloned = profile_mod.clone_config_with_platform_profile(
            config,
            platform="line",
            runtime_profile_key="secondary",
        )
        self.assertEqual(cloned.line.channel.secret, "secret-2")
        self.assertEqual(cloned.line.runtime_profile_key, "secondary")

    def test_legacy_profile_normalization_and_unknown_profile_key(self) -> None:
        config = profile_mod.build_config_namespace(
            {
                "basedir": "/tmp/mugen",
                "telegram": {
                    "webhook": {
                        "path_token": "legacy-token",
                        "secret_token": "legacy-secret",
                    }
                },
            }
        )

        sections = profile_mod.get_platform_profile_sections(
            config,
            platform="telegram",
        )
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].key, profile_mod.DEFAULT_RUNTIME_PROFILE_KEY)
        self.assertEqual(
            sections[0].runtime_profile_key,
            profile_mod.DEFAULT_RUNTIME_PROFILE_KEY,
        )

        with self.assertRaises(KeyError):
            profile_mod.get_platform_profile_section(
                config,
                platform="telegram",
                runtime_profile_key="missing",
            )

        with self.assertRaises(TypeError):
            profile_mod.clone_config_with_platform_profile(
                [],
                platform="telegram",
                runtime_profile_key="default",
            )

    def test_profile_helpers_cover_invalid_tables_and_missing_platform_sections(self) -> None:
        config = {"line": {"profiles": [[]]}}
        with self.assertRaises(RuntimeError):
            profile_mod.get_platform_profile_sections(config, platform="line")

        self.assertEqual(
            profile_mod.get_platform_profile_sections({}, platform="line"),
            (),
        )
        self.assertEqual(
            profile_mod.get_platform_profile_dicts({}, platform="line"),
            (),
        )
        self.assertEqual(
            profile_mod.get_platform_runtime_profile_keys({}, platform="line"),
            (),
        )

    def test_runtime_profile_scope_and_ingress_route_helpers(self) -> None:
        self.assertIsNone(profile_mod.normalize_runtime_profile_key(None))
        self.assertIsNone(profile_mod.normalize_runtime_profile_key("   "))
        self.assertEqual(
            profile_mod.normalize_runtime_profile_key(" secondary "),
            "secondary",
        )
        self.assertIsNone(profile_mod.runtime_profile_key_from_ingress_route(None))
        self.assertEqual(
            profile_mod.runtime_profile_key_from_ingress_route(
                {"runtime_profile_key": " default "}
            ),
            "default",
        )
        self.assertIsNone(profile_mod.get_active_runtime_profile_key())

        with profile_mod.runtime_profile_scope(" secondary "):
            self.assertEqual(
                profile_mod.get_active_runtime_profile_key(),
                "secondary",
            )

        self.assertIsNone(profile_mod.get_active_runtime_profile_key())

    def test_find_platform_runtime_profile_key_and_identifier_presence(self) -> None:
        config = profile_mod.build_config_namespace(self._config())

        self.assertEqual(
            profile_mod.find_platform_runtime_profile_key(
                config,
                platform="matrix",
                identifier_type="recipient_user_id",
                identifier_value="@bot-secondary:test",
            ),
            "secondary",
        )
        self.assertEqual(
            profile_mod.find_platform_runtime_profile_key(
                config,
                platform="wechat",
                identifier_type="path_token",
                identifier_value="wechat-default",
                filters={"provider": " official_account "},
            ),
            "default",
        )
        self.assertIsNone(
            profile_mod.find_platform_runtime_profile_key(
                config,
                platform="wechat",
                identifier_type="path_token",
                identifier_value="wechat-default",
                filters={"provider": "wecom"},
            )
        )
        self.assertIsNone(
            profile_mod.find_platform_runtime_profile_key(
                config,
                platform="wechat",
                identifier_type="path_token",
                identifier_value="wechat-default",
                filters={"unknown": "value"},
            )
        )
        self.assertIsNone(
            profile_mod.find_platform_runtime_profile_key(
                config,
                platform="line",
                identifier_type="unsupported",
                identifier_value="value",
            )
        )
        self.assertIsNone(
            profile_mod.find_platform_runtime_profile_key(
                config,
                platform="line",
                identifier_type="path_token",
                identifier_value=None,
            )
        )
        self.assertTrue(
            profile_mod.identifier_configured_for_platform(
                config,
                platform="telegram",
                identifier_type="secret_token",
            )
        )
        self.assertFalse(
            profile_mod.identifier_configured_for_platform(
                config,
                platform="telegram",
                identifier_type="missing",
            )
        )
        self.assertFalse(
            profile_mod.identifier_configured_for_platform(
                config,
                platform="telegram",
                identifier_type="   ",
            )
        )

    def test_private_helper_branches_cover_invalid_shapes_and_key_skips(self) -> None:
        with self.assertRaises(RuntimeError):
            profile_mod._normalize_required_text(  # pylint: disable=protected-access
                "   ",
                field_name="line.profiles[0].key",
            )

        namespace = SimpleNamespace(
            dict=None,
            name="profile",
            nested=SimpleNamespace(value=3),
        )
        setattr(namespace, "skip__", "ignored")
        self.assertEqual(
            profile_mod._plain_data(namespace),  # pylint: disable=protected-access
            {
                "name": "profile",
                "nested": {"value": 3},
            },
        )

        with patch.object(profile_mod, "_plain_data", return_value=[]):
            self.assertEqual(
                profile_mod._platform_section_dict(  # pylint: disable=protected-access
                    {"line": {"profiles": []}},
                    platform="line",
                ),
                {},
            )

        with patch.object(profile_mod, "to_namespace", return_value=[]):
            with self.assertRaises(TypeError):
                profile_mod.get_platform_profile_sections(
                    {"line": {"webhook": {"path_token": "legacy"}}},
                    platform="line",
                )

        with patch.object(
            profile_mod,
            "get_platform_profile_sections",
            return_value=(
                SimpleNamespace(key="default"),
                SimpleNamespace(key=None),
            ),
        ):
            self.assertEqual(
                profile_mod.get_platform_runtime_profile_keys(
                    {"line": {}},
                    platform="line",
                ),
                ("default",),
            )

        self.assertEqual(
            profile_mod._nested_value(  # pylint: disable=protected-access
                {"webhook": {"path_token": "abc"}},
                ("webhook", "path_token"),
            ),
            "abc",
        )
        self.assertEqual(
            profile_mod._deep_merge(  # pylint: disable=protected-access
                {"webhook": {"path_token": "old"}},
                {"webhook": {"path_token": "new"}},
            ),
            {"webhook": {"path_token": "new"}},
        )

        with (
            patch.object(
                profile_mod,
                "get_platform_profile_section",
                return_value=SimpleNamespace(),
            ),
            patch.object(
                profile_mod,
                "_plain_data",
                side_effect=[{"line": {"profiles": []}}, []],
            ),
        ):
            with self.assertRaises(TypeError):
                profile_mod.clone_config_with_platform_profile(
                    {"line": {"profiles": []}},
                    platform="line",
                    runtime_profile_key="default",
                )
