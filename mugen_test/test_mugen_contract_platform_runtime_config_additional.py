"""Additional branch tests for multi-profile runtime config validators."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mugen.core.contract.line_runtime_config import (
    validate_line_enabled_runtime_config,
)
from mugen.core.contract.matrix_runtime_config import (
    validate_matrix_enabled_runtime_config,
)
from mugen.core.contract.signal_runtime_config import (
    validate_signal_enabled_runtime_config,
)
from mugen.core.contract.telegram_runtime_config import (
    validate_telegram_enabled_runtime_config,
)
from mugen.core.contract.wechat_runtime_config import (
    validate_wechat_enabled_runtime_config,
)
from mugen.core.contract.whatsapp_runtime_config import (
    validate_whatsapp_enabled_runtime_config,
)


def _valid_line_config() -> dict:
    return {
        "line": {
            "webhook": {"dedupe_ttl_seconds": 60},
            "api": {
                "base_url": "https://api.line.me",
                "timeout_seconds": 10,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "media": {
                "allowed_mimetypes": ["image/png"],
                "max_download_bytes": 1024,
            },
            "typing": {"enabled": True},
            "profiles": [
                {
                    "key": "default",
                    "webhook": {"path_token": "line-path-1"},
                    "channel": {
                        "access_token": "token-1",
                        "secret": "secret-1",
                    },
                }
            ],
        }
    }


def _valid_matrix_config() -> dict:
    return {
        "matrix": {
            "domains": {"allowed": ["example.com"], "denied": []},
            "invites": {"direct_only": True},
            "media": {
                "allowed_mimetypes": ["image/png"],
                "max_download_bytes": 1024,
            },
            "security": {
                "device_trust": {
                    "mode": "strict_known",
                }
            },
            "profiles": [
                {
                    "key": "default",
                    "homeserver": "https://matrix.example.com",
                    "client": {
                        "user": "@bot-default:example.com",
                        "password": "password-1",
                    },
                }
            ],
        },
        "security": {
            "secrets": {
                "encryption_key": "0123456789abcdef0123456789abcdef",
            }
        },
    }


def _valid_signal_config() -> dict:
    return {
        "signal": {
            "api": {
                "timeout_seconds": 10,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "receive": {
                "heartbeat_seconds": 30,
                "reconnect_base_seconds": 1,
                "reconnect_max_seconds": 30,
                "reconnect_jitter_seconds": 0.5,
                "dedupe_ttl_seconds": 60,
            },
            "media": {
                "allowed_mimetypes": ["image/png"],
                "max_download_bytes": 1024,
            },
            "typing": {"enabled": True},
            "profiles": [
                {
                    "key": "default",
                    "account": {"number": "+15550001"},
                    "api": {
                        "base_url": "https://signal.example.com",
                        "bearer_token": "bearer-token",
                    },
                }
            ],
        }
    }


def _valid_telegram_config() -> dict:
    return {
        "telegram": {
            "webhook": {"dedupe_ttl_seconds": 60},
            "api": {
                "base_url": "https://api.telegram.org",
                "timeout_seconds": 10,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "media": {
                "allowed_mimetypes": ["image/png"],
                "max_download_bytes": 1024,
            },
            "typing": {"enabled": True},
            "profiles": [
                {
                    "key": "default",
                    "bot": {"token": "bot-token-1"},
                    "webhook": {
                        "path_token": "telegram-path-1",
                        "secret_token": "telegram-secret-1",
                    },
                }
            ],
        }
    }


def _valid_wechat_config() -> dict:
    return {
        "wechat": {
            "webhook": {"dedupe_ttl_seconds": 60},
            "api": {
                "timeout_seconds": 10,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
                "max_download_bytes": 1024,
            },
            "typing": {"enabled": True},
            "profiles": [
                {
                    "key": "default",
                    "provider": "official_account",
                    "webhook": {
                        "path_token": "wechat-path-1",
                        "signature_token": "wechat-signature-1",
                        "aes_enabled": False,
                    },
                    "official_account": {
                        "app_id": "app-id-1",
                        "app_secret": "app-secret-1",
                    },
                }
            ],
        }
    }


def _valid_whatsapp_config() -> dict:
    return {
        "mugen": {"beta": {"active": True}},
        "whatsapp": {
            "graphapi": {
                "timeout_seconds": 10,
                "max_download_bytes": 1024,
                "typing_indicator_enabled": True,
                "max_api_retries": 0,
                "retry_backoff_seconds": 0,
            },
            "servers": {
                "verify_ip": False,
                "allowed": "allowed.txt",
                "trust_forwarded_for": False,
            },
            "webhook": {
                "verification_token": "verification-token",
                "dedupe_ttl_seconds": 60,
            },
            "profiles": [
                {
                    "key": "default",
                    "business": {"phone_number_id": "phone-id-1"},
                    "app": {"secret": "app-secret-1"},
                }
            ],
        },
    }


class TestMuGenPlatformRuntimeConfigAdditional(unittest.TestCase):
    """Covers profile-array and uniqueness branches across validators."""

    def test_line_profiles_array_must_be_non_empty_and_keys_unique(self) -> None:
        empty_cfg = _valid_line_config()
        empty_cfg["line"]["profiles"] = []
        with self.assertRaisesRegex(RuntimeError, "line.profiles must be a non-empty array"):
            validate_line_enabled_runtime_config(empty_cfg)

        duplicate_cfg = _valid_line_config()
        duplicate_cfg["line"]["profiles"] = [
            duplicate_cfg["line"]["profiles"][0],
            {
                "key": "default",
                "webhook": {"path_token": "line-path-2"},
                "channel": {"access_token": "token-2", "secret": "secret-2"},
            },
        ]
        with self.assertRaisesRegex(RuntimeError, "line profile keys must be unique"):
            validate_line_enabled_runtime_config(duplicate_cfg)

    def test_matrix_profiles_array_must_be_non_empty_and_keys_unique(self) -> None:
        empty_cfg = _valid_matrix_config()
        empty_cfg["matrix"]["profiles"] = []
        with self.assertRaisesRegex(RuntimeError, "matrix.profiles must be a non-empty array"):
            validate_matrix_enabled_runtime_config(empty_cfg)

        duplicate_cfg = _valid_matrix_config()
        duplicate_cfg["matrix"]["profiles"] = [
            duplicate_cfg["matrix"]["profiles"][0],
            {
                "key": "default",
                "homeserver": "https://matrix-2.example.com",
                "client": {
                    "user": "@bot-secondary:example.com",
                    "password": "password-2",
                },
            },
        ]
        with self.assertRaisesRegex(RuntimeError, "matrix profile keys must be unique"):
            validate_matrix_enabled_runtime_config(duplicate_cfg)

    def test_signal_profiles_array_must_be_non_empty_and_keys_unique(self) -> None:
        empty_cfg = _valid_signal_config()
        empty_cfg["signal"]["profiles"] = []
        with self.assertRaisesRegex(RuntimeError, "signal.profiles must be a non-empty array"):
            validate_signal_enabled_runtime_config(empty_cfg)

        duplicate_cfg = _valid_signal_config()
        duplicate_cfg["signal"]["profiles"] = [
            duplicate_cfg["signal"]["profiles"][0],
            {
                "key": "default",
                "account": {"number": "+15550002"},
                "api": {
                    "base_url": "https://signal-2.example.com",
                    "bearer_token": "bearer-token-2",
                },
            },
        ]
        with self.assertRaisesRegex(RuntimeError, "signal profile keys must be unique"):
            validate_signal_enabled_runtime_config(duplicate_cfg)

    def test_telegram_profiles_branches_cover_empty_invalid_and_duplicate_values(
        self,
    ) -> None:
        empty_cfg = _valid_telegram_config()
        empty_cfg["telegram"]["profiles"] = []
        with self.assertRaisesRegex(RuntimeError, "telegram.profiles must be a non-empty array"):
            validate_telegram_enabled_runtime_config(empty_cfg)

        with patch(
            "mugen.core.contract.telegram_runtime_config.get_platform_profile_sections",
            return_value=(SimpleNamespace(),),
        ):
            with self.assertRaisesRegex(RuntimeError, "telegram.profiles\\[0\\] must be a table"):
                validate_telegram_enabled_runtime_config(_valid_telegram_config())

        duplicate_path_cfg = _valid_telegram_config()
        duplicate_path_cfg["telegram"]["profiles"] = [
            duplicate_path_cfg["telegram"]["profiles"][0],
            {
                "key": "secondary",
                "bot": {"token": "bot-token-2"},
                "webhook": {
                    "path_token": "telegram-path-1",
                    "secret_token": "telegram-secret-2",
                },
            },
        ]
        with self.assertRaisesRegex(
            RuntimeError,
            "telegram webhook path tokens must be unique",
        ):
            validate_telegram_enabled_runtime_config(duplicate_path_cfg)

        duplicate_secret_cfg = _valid_telegram_config()
        duplicate_secret_cfg["telegram"]["profiles"] = [
            duplicate_secret_cfg["telegram"]["profiles"][0],
            {
                "key": "secondary",
                "bot": {"token": "bot-token-2"},
                "webhook": {
                    "path_token": "telegram-path-2",
                    "secret_token": "telegram-secret-1",
                },
            },
        ]
        with self.assertRaisesRegex(
            RuntimeError,
            "telegram webhook secret tokens must be unique",
        ):
            validate_telegram_enabled_runtime_config(duplicate_secret_cfg)

    def test_wechat_profiles_array_must_be_non_empty_and_keys_unique(self) -> None:
        empty_cfg = _valid_wechat_config()
        empty_cfg["wechat"]["profiles"] = []
        with self.assertRaisesRegex(RuntimeError, "wechat.profiles must be a non-empty array"):
            validate_wechat_enabled_runtime_config(empty_cfg)

        duplicate_cfg = _valid_wechat_config()
        duplicate_cfg["wechat"]["profiles"] = [
            duplicate_cfg["wechat"]["profiles"][0],
            {
                "key": "default",
                "provider": "wecom",
                "webhook": {
                    "path_token": "wechat-path-2",
                    "signature_token": "wechat-signature-2",
                    "aes_enabled": False,
                },
                "wecom": {
                    "corp_id": "corp-1",
                    "agent_id": "agent-1",
                    "secret": "secret-1",
                },
            },
        ]
        with self.assertRaisesRegex(RuntimeError, "wechat profile keys must be unique"):
            validate_wechat_enabled_runtime_config(duplicate_cfg)

    def test_whatsapp_profiles_array_must_be_non_empty_and_keys_unique(self) -> None:
        empty_cfg = _valid_whatsapp_config()
        empty_cfg["whatsapp"]["profiles"] = []
        with self.assertRaisesRegex(RuntimeError, "whatsapp.profiles must be a non-empty array"):
            validate_whatsapp_enabled_runtime_config(empty_cfg)

        duplicate_cfg = _valid_whatsapp_config()
        duplicate_cfg["whatsapp"]["profiles"] = [
            duplicate_cfg["whatsapp"]["profiles"][0],
            {
                "key": "default",
                "business": {"phone_number_id": "phone-id-2"},
                "app": {"secret": "app-secret-2"},
            },
        ]
        with self.assertRaisesRegex(RuntimeError, "whatsapp profile keys must be unique"):
            validate_whatsapp_enabled_runtime_config(duplicate_cfg)
