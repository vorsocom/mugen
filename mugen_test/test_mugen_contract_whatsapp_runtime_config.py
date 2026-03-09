"""Tests for strict whatsapp runtime config contract validation."""

from __future__ import annotations

import copy
import re
import unittest

from mugen.core.contract.whatsapp_runtime_config import (
    validate_whatsapp_enabled_runtime_config,
)


def _valid_config() -> dict:
    return {
        "mugen": {},
        "whatsapp": {
            "app": {
                "id": "app-id",
                "secret": "whatsapp-app-secret",
            },
            "business": {
                "phone_number_id": "phone-number-id",
            },
            "graphapi": {
                "access_token": "graph-token",
                "base_url": "https://graph.facebook.com",
                "version": "v20.0",
                "timeout_seconds": 10.0,
                "max_download_bytes": 1024,
                "typing_indicator_enabled": True,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
            },
            "servers": {
                "allowed": "conf/whatsapp-allowed.txt",
                "verify_ip": False,
                "trust_forwarded_for": False,
            },
            "webhook": {
                "verification_token": "verification-token",
                "dedupe_ttl_seconds": 86400,
            },
        },
    }


class TestWhatsAppRuntimeConfigContract(unittest.TestCase):
    """Covers strict whatsapp-enabled runtime contract branches."""

    def test_accepts_valid_contracts(self) -> None:
        cfg = _valid_config()
        validate_whatsapp_enabled_runtime_config(cfg)

        cfg = _valid_config()
        cfg["mugen"] = None
        del cfg["whatsapp"]["graphapi"]["max_api_retries"]
        del cfg["whatsapp"]["graphapi"]["retry_backoff_seconds"]
        validate_whatsapp_enabled_runtime_config(cfg)

    def test_ignores_legacy_profiles_blocks(self) -> None:
        cfg = _valid_config()
        cfg["whatsapp"]["profiles"] = []
        validate_whatsapp_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_config()
        cfg["whatsapp"] = "invalid"
        cases.append((cfg, "whatsapp must be a table"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["base_url"] = ""
        cases.append((cfg, "whatsapp.graphapi.base_url"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["version"] = ""
        cases.append((cfg, "whatsapp.graphapi.version"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["timeout_seconds"] = 0
        cases.append((cfg, "whatsapp.graphapi.timeout_seconds"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["timeout_seconds"] = True
        cases.append((cfg, "whatsapp.graphapi.timeout_seconds"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["max_download_bytes"] = 0
        cases.append((cfg, "whatsapp.graphapi.max_download_bytes"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["max_download_bytes"] = True
        cases.append((cfg, "whatsapp.graphapi.max_download_bytes"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["typing_indicator_enabled"] = "true"
        cases.append((cfg, "whatsapp.graphapi.typing_indicator_enabled"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["max_api_retries"] = -1
        cases.append((cfg, "whatsapp.graphapi.max_api_retries"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["max_api_retries"] = True
        cases.append((cfg, "whatsapp.graphapi.max_api_retries"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["retry_backoff_seconds"] = -0.1
        cases.append((cfg, "whatsapp.graphapi.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["whatsapp"]["graphapi"]["retry_backoff_seconds"] = True
        cases.append((cfg, "whatsapp.graphapi.retry_backoff_seconds"))

        cfg = _valid_config()
        cfg["whatsapp"]["servers"]["verify_ip"] = "true"
        cases.append((cfg, "whatsapp.servers.verify_ip"))

        cfg = _valid_config()
        cfg["whatsapp"]["servers"]["verify_ip"] = True
        cfg["whatsapp"]["servers"]["allowed"] = ""
        cases.append((cfg, "whatsapp.servers.allowed"))

        cfg = _valid_config()
        cfg["whatsapp"]["servers"]["trust_forwarded_for"] = "true"
        cases.append((cfg, "whatsapp.servers.trust_forwarded_for"))

        cfg = _valid_config()
        cfg["whatsapp"]["webhook"]["dedupe_ttl_seconds"] = 0
        cases.append((cfg, "whatsapp.webhook.dedupe_ttl_seconds"))

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_whatsapp_enabled_runtime_config(copy.deepcopy(candidate))
