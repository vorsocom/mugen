"""Tests for strict telegram runtime config contract validation."""

from __future__ import annotations

import copy
import re
import unittest

from mugen.core.contract.telegram_runtime_config import (
    validate_telegram_enabled_runtime_config,
)


def _valid_config() -> dict:
    return {
        "telegram": {
            "bot": {
                "token": "token-123",
            },
            "webhook": {
                "path_token": "path-token-1",
                "secret_token": "secret-token-1",
                "dedupe_ttl_seconds": 86400,
            },
            "api": {
                "base_url": "https://api.telegram.org",
                "timeout_seconds": 10.0,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "media": {
                "allowed_mimetypes": ["audio/*", "image/*"],
                "max_download_bytes": 1024,
            },
            "typing": {
                "enabled": True,
            },
        }
    }


class TestTelegramRuntimeConfigContract(unittest.TestCase):
    """Covers strict telegram-enabled runtime contract branches."""

    def test_accepts_valid_contracts(self) -> None:
        cfg = _valid_config()
        validate_telegram_enabled_runtime_config(cfg)

    def test_ignores_legacy_profiles_blocks(self) -> None:
        cfg = _valid_config()
        cfg["telegram"]["profiles"] = []
        validate_telegram_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_config()
        cfg["telegram"] = "invalid"
        cases.append((cfg, "telegram must be a table"))

        cfg = _valid_config()
        cfg["telegram"]["webhook"]["dedupe_ttl_seconds"] = 0
        cases.append((cfg, "telegram.webhook.dedupe_ttl_seconds"))

        cfg = _valid_config()
        cfg["telegram"]["api"]["base_url"] = ""
        cases.append((cfg, "telegram.api.base_url"))

        cfg = _valid_config()
        cfg["telegram"]["api"]["timeout_seconds"] = 0
        cases.append((cfg, "telegram.api.timeout_seconds"))

        cfg = _valid_config()
        cfg["telegram"]["api"]["timeout_seconds"] = True
        cases.append((cfg, "telegram.api.timeout_seconds"))

        cfg = _valid_config()
        cfg["telegram"]["api"]["max_api_retries"] = True
        cases.append((cfg, "telegram.api.max_api_retries"))

        cfg = _valid_config()
        cfg["telegram"]["api"]["retry_backoff_seconds"] = -0.1
        cases.append((cfg, "telegram.api.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["telegram"]["api"]["retry_backoff_seconds"] = True
        cases.append((cfg, "telegram.api.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["telegram"]["media"]["allowed_mimetypes"] = []
        cases.append((cfg, "telegram.media.allowed_mimetypes"))

        cfg = _valid_config()
        cfg["telegram"]["media"]["allowed_mimetypes"] = [""]
        cases.append((cfg, "telegram.media.allowed_mimetypes[0]"))

        cfg = _valid_config()
        cfg["telegram"]["media"]["max_download_bytes"] = 0
        cases.append((cfg, "telegram.media.max_download_bytes"))

        cfg = _valid_config()
        cfg["telegram"]["typing"]["enabled"] = "true"
        cases.append((cfg, "telegram.typing.enabled"))

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_telegram_enabled_runtime_config(copy.deepcopy(candidate))
