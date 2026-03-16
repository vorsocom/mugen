"""Tests for strict matrix runtime config contract validation."""

from __future__ import annotations

import copy
import re
import unittest

from mugen.core.contract.matrix_runtime_config import (
    validate_matrix_enabled_runtime_config,
)


def _valid_config() -> dict:
    return {
        "matrix": {
            "homeserver": "https://matrix.example.com",
            "client": {
                "user": "@assistant:example.com",
                "password": "pw",
            },
            "invites": {
                "direct_only": True,
            },
            "media": {
                "allowed_mimetypes": ["image/*", "video/*"],
                "max_download_bytes": 1024,
            },
            "security": {
                "device_trust": {
                    "mode": "strict_known",
                    "allowlist": [],
                },
                "credentials": {
                    "encryption_key": "0123456789abcdef0123456789abcdef",
                },
            },
        },
    }


class TestMatrixRuntimeConfigContract(unittest.TestCase):
    """Covers strict matrix-enabled runtime contract branches."""

    def test_accepts_valid_contracts(self) -> None:
        cfg = _valid_config()
        validate_matrix_enabled_runtime_config(cfg)

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "permissive"
        validate_matrix_enabled_runtime_config(cfg)

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "@user:example.com",
                "device_ids": ["DEV-1"],
            }
        ]
        validate_matrix_enabled_runtime_config(cfg)

    def test_ignores_legacy_profiles_blocks(self) -> None:
        cfg = _valid_config()
        cfg["matrix"]["profiles"] = []
        validate_matrix_enabled_runtime_config(cfg)

    def test_tolerates_legacy_root_domains_block(self) -> None:
        cfg = _valid_config()
        cfg["matrix"]["domains"] = "invalid"
        validate_matrix_enabled_runtime_config(cfg)

        cfg = _valid_config()
        cfg["matrix"]["domains"] = {
            "allowed": [],
            "denied": "blocked.example.com",
        }
        validate_matrix_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_config()
        cfg["matrix"] = "invalid"
        cases.append((cfg, "matrix must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["invites"] = "invalid"
        cases.append((cfg, "matrix.invites must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["invites"]["direct_only"] = "true"
        cases.append((cfg, "matrix.invites.direct_only must be a boolean"))

        cfg = _valid_config()
        cfg["matrix"]["media"] = "invalid"
        cases.append((cfg, "matrix.media must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["media"]["allowed_mimetypes"] = []
        cases.append((cfg, "matrix.media.allowed_mimetypes must be a non-empty array of strings"))

        cfg = _valid_config()
        cfg["matrix"]["media"]["allowed_mimetypes"] = [""]
        cases.append((cfg, "matrix.media.allowed_mimetypes[0] must be a non-empty string"))

        cfg = _valid_config()
        cfg["matrix"]["media"]["max_download_bytes"] = True
        cases.append((cfg, "matrix.media.max_download_bytes must be a positive integer"))

        cfg = _valid_config()
        cfg["matrix"]["media"]["max_download_bytes"] = "10"
        cases.append((cfg, "matrix.media.max_download_bytes must be a positive integer"))

        cfg = _valid_config()
        cfg["matrix"]["media"]["max_download_bytes"] = 0
        cases.append((cfg, "matrix.media.max_download_bytes must be a positive integer"))

        cfg = _valid_config()
        cfg["matrix"]["security"] = "invalid"
        cases.append((cfg, "matrix.security must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"] = "invalid"
        cases.append((cfg, "matrix.security.device_trust must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = ""
        cases.append((cfg, "matrix.security.device_trust.mode"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "unsupported"
        cases.append((cfg, "matrix.security.device_trust.mode must be one of"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = "invalid"
        cases.append((cfg, "matrix.security.device_trust.allowlist must be an array"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = []
        cases.append((cfg, "must be a non-empty array when mode=allowlist"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [object()]
        cases.append((cfg, "allowlist[0] must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "",
                "device_ids": ["DEV-1"],
            }
        ]
        cases.append((cfg, "allowlist[0].user_id must be a non-empty string"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "@user:example.com",
                "device_ids": [],
            }
        ]
        cases.append((cfg, "allowlist[0].device_ids must be a non-empty array of strings"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "@user:example.com",
                "device_ids": ["DEV-1", ""],
            }
        ]
        cases.append((cfg, "allowlist[0].device_ids[1] must be a non-empty string"))

        cfg = _valid_config()
        cfg["matrix"]["security"]["credentials"] = "invalid"
        cases.append(
            (
                cfg,
                "matrix.security.credentials.encryption_key is required when matrix platform is enabled",
            )
        )

        cfg = _valid_config()
        cfg["matrix"]["security"]["credentials"] = {"encryption_key": "   "}
        cases.append(
            (
                cfg,
                "matrix.security.credentials.encryption_key must be non-empty",
            )
        )

        cfg = _valid_config()
        cfg["matrix"]["security"]["credentials"] = {"encryption_key": "short"}
        cases.append(
            (
                cfg,
                "matrix.security.credentials.encryption_key must contain at least 32 characters",
            )
        )

        cfg = _valid_config()
        cfg["matrix"]["security"]["credentials"] = {
            "encryption_key": "<set-secret-encryption-key>"
        }
        cases.append(
            (
                cfg,
                "matrix.security.credentials.encryption_key must not use placeholder values",
            )
        )

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_matrix_enabled_runtime_config(copy.deepcopy(candidate))
