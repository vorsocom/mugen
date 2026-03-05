"""Tests for strict wechat runtime config contract validation."""

from __future__ import annotations

import copy
import re
import unittest

from mugen.core.contract.wechat_runtime_config import (
    validate_wechat_enabled_runtime_config,
)


def _valid_oa_config() -> dict:
    return {
        "wechat": {
            "provider": "official_account",
            "webhook": {
                "path_token": "path-token-1",
                "signature_token": "signature-token-1",
                "aes_enabled": False,
                "aes_key": "0123456789abcdef0123456789abcdef0123456789A",
                "dedupe_ttl_seconds": 86400,
            },
            "api": {
                "timeout_seconds": 10.0,
                "max_api_retries": 2,
                "retry_backoff_seconds": 0.5,
                "max_download_bytes": 2048,
            },
            "typing": {
                "enabled": True,
            },
            "official_account": {
                "app_id": "wx-app-id",
                "app_secret": "wx-app-secret",
            },
            "wecom": {
                "corp_id": "corp-id",
                "corp_secret": "corp-secret",
                "agent_id": 1000002,
            },
        }
    }


class TestWeChatRuntimeConfigContract(unittest.TestCase):
    """Covers strict wechat-enabled runtime contract branches."""

    def test_accepts_valid_contracts_for_oa_and_wecom(self) -> None:
        cfg = _valid_oa_config()
        validate_wechat_enabled_runtime_config(cfg)

        cfg = _valid_oa_config()
        cfg["wechat"]["provider"] = "wecom"
        validate_wechat_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_oa_config()
        cfg["wechat"] = "invalid"
        cases.append((cfg, "wechat must be a table"))

        cfg = _valid_oa_config()
        cfg["wechat"]["provider"] = "unknown"
        cases.append((cfg, "wechat.provider"))

        cfg = _valid_oa_config()
        cfg["wechat"]["webhook"]["path_token"] = ""
        cases.append((cfg, "wechat.webhook.path_token"))

        cfg = _valid_oa_config()
        cfg["wechat"]["webhook"]["signature_token"] = ""
        cases.append((cfg, "wechat.webhook.signature_token"))

        cfg = _valid_oa_config()
        cfg["wechat"]["webhook"]["aes_enabled"] = "true"
        cases.append((cfg, "wechat.webhook.aes_enabled"))

        cfg = _valid_oa_config()
        cfg["wechat"]["webhook"]["aes_enabled"] = True
        cfg["wechat"]["webhook"]["aes_key"] = ""
        cases.append((cfg, "wechat.webhook.aes_key"))

        cfg = _valid_oa_config()
        cfg["wechat"]["webhook"]["dedupe_ttl_seconds"] = 0
        cases.append((cfg, "wechat.webhook.dedupe_ttl_seconds"))

        cfg = _valid_oa_config()
        cfg["wechat"]["api"]["timeout_seconds"] = 0
        cases.append((cfg, "wechat.api.timeout_seconds"))

        cfg = _valid_oa_config()
        cfg["wechat"]["api"]["timeout_seconds"] = True
        cases.append((cfg, "wechat.api.timeout_seconds"))

        cfg = _valid_oa_config()
        cfg["wechat"]["api"]["max_api_retries"] = True
        cases.append((cfg, "wechat.api.max_api_retries"))

        cfg = _valid_oa_config()
        cfg["wechat"]["api"]["retry_backoff_seconds"] = -0.1
        cases.append((cfg, "wechat.api.retry_backoff_seconds"))

        cfg = _valid_oa_config()
        cfg["wechat"]["api"]["retry_backoff_seconds"] = True
        cases.append((cfg, "wechat.api.retry_backoff_seconds"))

        cfg = _valid_oa_config()
        cfg["wechat"]["api"]["max_download_bytes"] = 0
        cases.append((cfg, "wechat.api.max_download_bytes"))

        cfg = _valid_oa_config()
        cfg["wechat"]["typing"]["enabled"] = "true"
        cases.append((cfg, "wechat.typing.enabled"))

        cfg = _valid_oa_config()
        cfg["wechat"]["official_account"]["app_id"] = ""
        cases.append((cfg, "wechat.official_account.app_id"))

        cfg = _valid_oa_config()
        cfg["wechat"]["provider"] = "wecom"
        cfg["wechat"]["wecom"]["corp_id"] = ""
        cases.append((cfg, "wechat.wecom.corp_id"))

        cfg = _valid_oa_config()
        cfg["wechat"]["provider"] = "wecom"
        cfg["wechat"]["wecom"]["corp_secret"] = ""
        cases.append((cfg, "wechat.wecom.corp_secret"))

        cfg = _valid_oa_config()
        cfg["wechat"]["provider"] = "wecom"
        cfg["wechat"]["wecom"]["agent_id"] = 0
        cases.append((cfg, "wechat.wecom.agent_id"))

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_wechat_enabled_runtime_config(copy.deepcopy(candidate))
