"""Focused tests for ACP runtime config policy normalization helpers."""

from __future__ import annotations

import unittest
import uuid

from mugen.core.plugin.acp.utility import runtime_config_policy as policy


class TestRuntimeConfigPolicy(unittest.TestCase):
    """Covers allowlist, normalization, and validation helper branches."""

    def test_normalize_json_object_and_leaf_iteration(self) -> None:
        self.assertEqual(
            policy.normalize_json_object(None, field_name="Settings"),
            {},
        )
        self.assertEqual(
            policy.normalize_json_object(
                {
                    "Outer": {
                        "Items": [
                            {"Inner": 1},
                            {},
                        ]
                    }
                },
                field_name="Settings",
            ),
            {
                "outer": {
                    "items": [
                        {"inner": 1},
                        {},
                    ]
                }
            },
        )
        self.assertEqual(
            list(
                policy._iter_leaf_paths(  # pylint: disable=protected-access
                    {"webhook": {}}
                )
            ),
            [(("webhook",), {})],
        )

        with self.assertRaisesRegex(RuntimeError, "Settings must be a JSON object"):
            policy.normalize_json_object([], field_name="Settings")

        with self.assertRaisesRegex(RuntimeError, "duplicate key 'a'"):
            policy.normalize_json_object(
                {"A": 1, "a": 2},
                field_name="Settings",
            )

    def test_messaging_platform_settings_and_secret_refs(self) -> None:
        key_ref_id = str(uuid.uuid4())

        self.assertEqual(
            policy.normalize_messaging_platform_key(" MATRIX "),
            "matrix",
        )
        self.assertEqual(
            policy.normalize_tenant_messaging_settings(
                platform_key="wechat",
                value={"Webhook": {"Aes_Enabled": True}},
            ),
            {"webhook": {"aes_enabled": True}},
        )
        self.assertEqual(
            policy.normalize_messaging_client_profile_settings(
                platform_key="matrix",
                value={
                    "Client": {"Device": "device-1"},
                    "Federation": {
                        "Allowed": ["example.com"],
                        "Denied": ["blocked.example.com"],
                    },
                    "User_Access": {
                        "Mode": "allow-only",
                        "Users": ["@user:example.com"],
                    },
                },
            ),
            {
                "client": {"device": "device-1"},
                "federation": {
                    "allowed": ["example.com"],
                    "denied": ["blocked.example.com"],
                },
                "user_access": {
                    "mode": "allow-only",
                    "users": ["@user:example.com"],
                },
            },
        )
        self.assertEqual(
            policy.normalize_secret_ref_map(
                platform_key="matrix",
                value={"CLIENT.PASSWORD": key_ref_id},
            ),
            {"client.password": key_ref_id},
        )
        self.assertEqual(
            policy.normalize_secret_ref_map(platform_key="line", value=None),
            {},
        )

        with self.assertRaisesRegex(RuntimeError, "PlatformKey must be one of"):
            policy.normalize_messaging_platform_key("email")

        with self.assertRaisesRegex(
            RuntimeError,
            "Settings path 'webhook.pathtoken' is not allowed",
        ):
            policy.normalize_tenant_messaging_settings(
                platform_key="telegram",
                value={"Webhook": {"PathToken": "blocked"}},
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "SettingsJson path 'user_access.mode' is not allowed",
        ):
            policy.normalize_runtime_config_settings(
                category="messaging.platform_defaults",
                profile_key="matrix",
                value={"User_Access": {"Mode": "allow-only"}},
            )
        with self.assertRaisesRegex(
            RuntimeError,
            "SettingsJson path 'federation.allowed' is not allowed",
        ):
            policy.normalize_runtime_config_settings(
                category="messaging.platform_defaults",
                profile_key="matrix",
                value={"Federation": {"Allowed": ["example.com"]}},
            )

        with self.assertRaisesRegex(RuntimeError, "SecretRefs must be a JSON object"):
            policy.normalize_secret_ref_map(
                platform_key="matrix",
                value=[],
            )

        with self.assertRaisesRegex(RuntimeError, "SecretRefs key must be non-empty"):
            policy.normalize_secret_ref_map(
                platform_key="matrix",
                value={" . ": key_ref_id},
            )

        with self.assertRaisesRegex(RuntimeError, "must be a valid KeyRef UUID"):
            policy.normalize_secret_ref_map(
                platform_key="matrix",
                value={"client.password": "not-a-uuid"},
            )

    def test_runtime_config_category_profile_and_settings(self) -> None:
        self.assertEqual(
            policy.normalize_runtime_config_category(" OPS_CONNECTOR.DEFAULTS "),
            "ops_connector.defaults",
        )
        self.assertEqual(
            policy.normalize_runtime_config_profile_key(
                category="messaging.platform_defaults",
                value="WHATSAPP",
            ),
            "whatsapp",
        )
        self.assertEqual(
            policy.normalize_runtime_config_settings(
                category="ops_connector.defaults",
                profile_key="default",
                value={
                    "Retry_Status_Codes_Default": [429, 503],
                    "Redacted_Keys": ["secret"],
                },
            ),
            {
                "retry_status_codes_default": [429, 503],
                "redacted_keys": ["secret"],
            },
        )
        self.assertEqual(
            policy.normalize_runtime_config_settings(
                category="messaging.platform_defaults",
                profile_key="matrix",
                value={
                    "Homeserver": "https://matrix.example.com",
                    "Client": {"Device": "device-1"},
                },
            ),
            {
                "homeserver": "https://matrix.example.com",
                "client": {"device": "device-1"},
            },
        )

        with self.assertRaisesRegex(RuntimeError, "Category must be one of"):
            policy.normalize_runtime_config_category("unsupported")

        with self.assertRaisesRegex(RuntimeError, "Category must be non-empty"):
            policy.normalize_runtime_config_category(" ")

        with self.assertRaisesRegex(RuntimeError, "ProfileKey must be 'default'"):
            policy.normalize_runtime_config_profile_key(
                category="ops_connector.defaults",
                value="tenant-a",
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "SettingsJson path 'secret_purpose' is not allowed",
        ):
            policy.normalize_runtime_config_settings(
                category="ops_connector.defaults",
                profile_key="default",
                value={"Secret_Purpose": "operator-only"},
            )


if __name__ == "__main__":
    unittest.main()
