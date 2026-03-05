"""Tests for strict signal runtime config contract validation."""

from __future__ import annotations

import copy
import re
import unittest

from mugen.core.contract.signal_runtime_config import (
    validate_signal_enabled_runtime_config,
)


def _valid_config() -> dict:
    return {
        "signal": {
            "account": {
                "number": "+15550000001",
            },
            "api": {
                "base_url": "http://127.0.0.1:8080",
                "bearer_token": "token-1",
                "timeout_seconds": 10.0,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "receive": {
                "heartbeat_seconds": 30.0,
                "reconnect_base_seconds": 1.0,
                "reconnect_max_seconds": 30.0,
                "reconnect_jitter_seconds": 0.25,
                "dedupe_ttl_seconds": 86400,
            },
            "media": {
                "allowed_mimetypes": ["audio/*", "image/*"],
                "max_download_bytes": 20_971_520,
            },
            "typing": {
                "enabled": True,
            },
        }
    }


class TestSignalRuntimeConfigContract(unittest.TestCase):
    """Covers strict signal-enabled runtime contract branches."""

    def test_accepts_valid_contracts(self) -> None:
        cfg = _valid_config()
        validate_signal_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_config()
        cfg["signal"] = "invalid"
        cases.append((cfg, "signal must be a table"))

        cfg = _valid_config()
        cfg["signal"]["account"]["number"] = ""
        cases.append((cfg, "signal.account.number"))

        cfg = _valid_config()
        cfg["signal"]["api"]["base_url"] = ""
        cases.append((cfg, "signal.api.base_url"))

        cfg = _valid_config()
        cfg["signal"]["api"]["bearer_token"] = ""
        cases.append((cfg, "signal.api.bearer_token"))

        cfg = _valid_config()
        cfg["signal"]["api"]["timeout_seconds"] = 0
        cases.append((cfg, "signal.api.timeout_seconds"))

        cfg = _valid_config()
        cfg["signal"]["api"]["timeout_seconds"] = True
        cases.append((cfg, "signal.api.timeout_seconds"))

        cfg = _valid_config()
        cfg["signal"]["api"]["max_api_retries"] = 0
        cases.append((cfg, "signal.api.max_api_retries"))

        cfg = _valid_config()
        cfg["signal"]["api"]["max_api_retries"] = True
        cases.append((cfg, "signal.api.max_api_retries"))

        cfg = _valid_config()
        cfg["signal"]["api"]["retry_backoff_seconds"] = -0.1
        cases.append((cfg, "signal.api.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["signal"]["api"]["retry_backoff_seconds"] = True
        cases.append((cfg, "signal.api.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["signal"]["receive"]["heartbeat_seconds"] = 0
        cases.append((cfg, "signal.receive.heartbeat_seconds"))

        cfg = _valid_config()
        cfg["signal"]["receive"]["reconnect_base_seconds"] = -1
        cases.append((cfg, "signal.receive.reconnect_base_seconds"))

        cfg = _valid_config()
        cfg["signal"]["receive"]["reconnect_max_seconds"] = True
        cases.append((cfg, "signal.receive.reconnect_max_seconds"))

        cfg = _valid_config()
        cfg["signal"]["receive"]["reconnect_jitter_seconds"] = True
        cases.append((cfg, "signal.receive.reconnect_jitter_seconds"))

        cfg = _valid_config()
        cfg["signal"]["receive"]["dedupe_ttl_seconds"] = 0
        cases.append((cfg, "signal.receive.dedupe_ttl_seconds"))

        cfg = _valid_config()
        cfg["signal"]["media"]["allowed_mimetypes"] = []
        cases.append((cfg, "signal.media.allowed_mimetypes"))

        cfg = _valid_config()
        cfg["signal"]["media"]["allowed_mimetypes"] = [""]
        cases.append((cfg, "signal.media.allowed_mimetypes[0]"))

        cfg = _valid_config()
        cfg["signal"]["media"]["max_download_bytes"] = 0
        cases.append((cfg, "signal.media.max_download_bytes"))

        cfg = _valid_config()
        cfg["signal"]["typing"]["enabled"] = "true"
        cases.append((cfg, "signal.typing.enabled"))

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_signal_enabled_runtime_config(copy.deepcopy(candidate))
