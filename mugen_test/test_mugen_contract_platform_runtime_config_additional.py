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
                },
                "credentials": {
                    "encryption_key": "0123456789abcdef0123456789abcdef",
                },
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
    }


def _valid_signal_config() -> dict:
    return {
        "signal": {
            "api": {
                "base_url": "https://signal.example.com",
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
            "beta": {
                "users": ["15550000001"],
            },
            "graphapi": {
                "base_url": "https://graph.facebook.com",
                "version": "v20.0",
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
    """Covers legacy profile-block tolerance across validators."""

    def test_line_validator_tolerates_empty_profiles_array(self) -> None:
        cfg = _valid_line_config()
        cfg["line"]["profiles"] = []
        validate_line_enabled_runtime_config(cfg)

    def test_matrix_validator_tolerates_empty_profiles_array(self) -> None:
        cfg = _valid_matrix_config()
        cfg["matrix"]["profiles"] = []
        validate_matrix_enabled_runtime_config(cfg)

    def test_signal_validator_tolerates_empty_profiles_array(self) -> None:
        cfg = _valid_signal_config()
        cfg["signal"]["profiles"] = []
        validate_signal_enabled_runtime_config(cfg)

    def test_telegram_validator_tolerates_empty_profiles_array(self) -> None:
        cfg = _valid_telegram_config()
        cfg["telegram"]["profiles"] = []
        validate_telegram_enabled_runtime_config(cfg)

    def test_wechat_validator_tolerates_empty_profiles_array(self) -> None:
        cfg = _valid_wechat_config()
        cfg["wechat"]["profiles"] = []
        validate_wechat_enabled_runtime_config(cfg)

    def test_whatsapp_validator_tolerates_empty_profiles_array(self) -> None:
        cfg = _valid_whatsapp_config()
        cfg["whatsapp"]["profiles"] = []
        validate_whatsapp_enabled_runtime_config(cfg)
