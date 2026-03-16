"""Tests for strict line runtime config contract validation."""

from __future__ import annotations

import copy
import re
import unittest

from mugen.core.contract.line_runtime_config import (
    validate_line_enabled_runtime_config,
)


def _valid_config() -> dict:
    return {
        "line": {
            "channel": {
                "access_token": "line-token",
                "secret": "line-secret",
            },
            "webhook": {
                "path_token": "path-token",
                "dedupe_ttl_seconds": 86400,
            },
            "api": {
                "base_url": "https://api.line.me",
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


class TestLineRuntimeConfigContract(unittest.TestCase):
    """Covers strict line-enabled runtime contract branches."""

    def test_accepts_valid_contracts(self) -> None:
        cfg = _valid_config()
        validate_line_enabled_runtime_config(cfg)

    def test_ignores_legacy_profiles_blocks(self) -> None:
        cfg = _valid_config()
        cfg["line"]["profiles"] = []
        validate_line_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_config()
        cfg["line"] = "invalid"
        cases.append((cfg, "line must be a table"))

        cfg = _valid_config()
        cfg["line"]["webhook"]["dedupe_ttl_seconds"] = 0
        cases.append((cfg, "line.webhook.dedupe_ttl_seconds"))

        cfg = _valid_config()
        cfg["line"]["api"]["base_url"] = ""
        cases.append((cfg, "line.api.base_url"))

        cfg = _valid_config()
        cfg["line"]["api"]["timeout_seconds"] = 0
        cases.append((cfg, "line.api.timeout_seconds"))

        cfg = _valid_config()
        cfg["line"]["api"]["timeout_seconds"] = True
        cases.append((cfg, "line.api.timeout_seconds"))

        cfg = _valid_config()
        cfg["line"]["api"]["max_api_retries"] = True
        cases.append((cfg, "line.api.max_api_retries"))

        cfg = _valid_config()
        cfg["line"]["api"]["retry_backoff_seconds"] = -0.1
        cases.append((cfg, "line.api.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["line"]["api"]["retry_backoff_seconds"] = True
        cases.append((cfg, "line.api.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["line"]["media"]["allowed_mimetypes"] = []
        cases.append((cfg, "line.media.allowed_mimetypes"))

        cfg = _valid_config()
        cfg["line"]["media"]["allowed_mimetypes"] = [""]
        cases.append((cfg, "line.media.allowed_mimetypes[0]"))

        cfg = _valid_config()
        cfg["line"]["media"]["max_download_bytes"] = 0
        cases.append((cfg, "line.media.max_download_bytes"))

        cfg = _valid_config()
        cfg["line"]["typing"]["enabled"] = "true"
        cases.append((cfg, "line.typing.enabled"))

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_line_enabled_runtime_config(copy.deepcopy(candidate))
