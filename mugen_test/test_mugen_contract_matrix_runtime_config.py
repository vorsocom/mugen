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
            "domains": {
                "allowed": ["example.com"],
                "denied": [],
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
                }
            },
        },
        "security": {
            "secrets": {
                "encryption_key": "0123456789abcdef0123456789abcdef",
            }
        },
    }


class TestMatrixRuntimeConfigContract(unittest.TestCase):
    """Covers strict matrix-enabled runtime contract branches."""

    def test_accepts_valid_contracts(self) -> None:
        cfg = _valid_config()
        validate_matrix_enabled_runtime_config(cfg)

        cfg = _valid_config()
        cfg["matrix"]["domains"]["denied"] = ["blocked.example.com"]
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

    def test_accepts_profiles_and_rejects_duplicate_client_users(self) -> None:
        cfg = _valid_config()
        cfg["matrix"]["profiles"] = [
            {
                "key": "default",
                "homeserver": "https://matrix-a.example.com",
                "client": {
                    "user": "@assistant-a:example.com",
                    "password": "pw-a",
                },
            },
            {
                "key": "secondary",
                "homeserver": "https://matrix-b.example.com",
                "client": {
                    "user": "@assistant-b:example.com",
                    "password": "pw-b",
                },
            },
        ]
        validate_matrix_enabled_runtime_config(cfg)

        cfg = copy.deepcopy(cfg)
        cfg["matrix"]["profiles"][1]["client"]["user"] = "@assistant-a:example.com"
        with self.assertRaisesRegex(
            RuntimeError,
            re.escape("matrix client.user values must be unique"),
        ):
            validate_matrix_enabled_runtime_config(cfg)

    def test_rejects_invalid_shapes_and_values(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_config()
        cfg["matrix"] = "invalid"
        cases.append((cfg, "matrix must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["homeserver"] = "   "
        cases.append((cfg, "matrix.homeserver"))

        cfg = _valid_config()
        cfg["matrix"]["client"] = "invalid"
        cases.append((cfg, "matrix.client must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["client"]["user"] = ""
        cases.append((cfg, "matrix.client.user"))

        cfg = _valid_config()
        cfg["matrix"]["client"]["password"] = ""
        cases.append((cfg, "matrix.client.password"))

        cfg = _valid_config()
        cfg["matrix"]["domains"] = "invalid"
        cases.append((cfg, "matrix.domains must be a table"))

        cfg = _valid_config()
        cfg["matrix"]["domains"]["allowed"] = []
        cases.append((cfg, "matrix.domains.allowed must be a non-empty array of strings"))

        cfg = _valid_config()
        cfg["matrix"]["domains"]["allowed"] = ["", "ok"]
        cases.append((cfg, "matrix.domains.allowed[0] must be a non-empty string"))

        cfg = _valid_config()
        cfg["matrix"]["domains"]["denied"] = "example.com"
        cases.append((cfg, "matrix.domains.denied must be an array of strings"))

        cfg = _valid_config()
        cfg["matrix"]["domains"]["denied"] = ["", "example.com"]
        cases.append((cfg, "matrix.domains.denied[0] must be a non-empty string"))

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
        cfg["security"] = "invalid"
        cases.append(
            (
                cfg,
                "security.secrets.encryption_key is required when matrix platform is enabled",
            )
        )

        cfg = _valid_config()
        cfg["security"] = {"secrets": {"encryption_key": "   "}}
        cases.append(
            (
                cfg,
                "security.secrets.encryption_key must be non-empty",
            )
        )

        cfg = _valid_config()
        cfg["security"] = {"secrets": {"encryption_key": "short"}}
        cases.append((cfg, "security.secrets.encryption_key must contain at least 32 characters"))

        cfg = _valid_config()
        cfg["security"] = {"secrets": {"encryption_key": "<set-secret-encryption-key>"}}
        cases.append((cfg, "security.secrets.encryption_key must not use placeholder values"))

        for candidate, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, re.escape(pattern)):
                    validate_matrix_enabled_runtime_config(copy.deepcopy(candidate))
