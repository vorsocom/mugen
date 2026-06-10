"""Tests for deployment environment config overlays."""

import json
from pathlib import Path
from textwrap import dedent
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from werkzeug.security import check_password_hash

from mugen.core import di
from mugen.core.contract.migration_config import load_mugen_config
from mugen.core.utility import deployment_config as deployment_config_module
from mugen.core.utility.deployment_config import (
    apply_environment_overrides,
    parse_log_level,
    validate_production_deployment_config,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LOCAL_ADMIN_PASSWORD = "LocalAdmin1!"
_LOCAL_ADMIN_PASSWORD_HASH = (
    "scrypt:32768:8:1$Hwq89E662mEFoypg$"
    "9389cc28be5125f0b9e66f9770a877ff1c502f0ba3c86e69f682a928b3c251e9b8aac8e8a969201523eda4245fffb14c0d5478452d8d1890c8dd678af117c7a3"
)
_OLD_TEST_PRIVATE_PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "old-not-a-real-test-key\n"
    "-----END PRIVATE KEY-----\n"
)
_NEW_TEST_PRIVATE_PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "new-not-a-real-test-key\n"
    "-----END PRIVATE KEY-----\n"
)


def _sample_core_extension_entries() -> list[dict]:
    entries: list[dict] = []
    current: dict | None = None
    sample_path = _REPO_ROOT / "conf" / "mugen.toml.sample"

    for raw_line in sample_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        normalized = stripped[1:].strip() if stripped.startswith("#") else stripped

        if normalized == "[[mugen.modules.extensions]]":
            if current:
                entries.append(current)
            current = {}
            continue

        if current is None:
            continue

        if normalized == "" or normalized.startswith("["):
            if current:
                entries.append(current)
            current = None
            continue

        if "=" not in normalized:
            continue

        key, raw_value = normalized.split("=", 1)
        key = key.strip()
        if key not in {
            "type",
            "token",
            "enabled",
            "name",
            "namespace",
            "models",
            "migration_track",
            "contrib",
        }:
            continue

        value: object = raw_value.strip()
        if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif isinstance(value, str) and value.lower() == "true":
            value = True
        elif isinstance(value, str) and value.lower() == "false":
            value = False

        current[key] = value

    if current:
        entries.append(current)

    return [
        entry
        for entry in entries
        if str(entry.get("token", "")).startswith("core.")
    ]


def _real_ed25519_private_pem() -> str:
    private_key = ed25519.Ed25519PrivateKey.generate()
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def _jwt_config_json(
    *,
    active_kid: str = "prod-key",
    keys: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "active_kid": active_kid,
            "issuer": "mugen",
            "audience": "mugen",
            "keys": (
                keys
                if keys is not None
                else [
                    {
                        "kid": "prod-key",
                        "alg": "EdDSA",
                        "pem": _NEW_TEST_PRIVATE_PEM,
                    }
                ]
            ),
        }
    )


def _base_config() -> dict:
    return {
        "mugen": {
            "environment": "development",
            "logger": {
                "level": 10,
                "name": "COM.VORSOCOMPUTING.MUGEN",
            },
            "modules": {
                "extensions": [],
            },
        },
        "quart": {
            "secret_key": "0123456789abcdef0123456789abcdef",
        },
        "acp": {
            "cors_origins": ["*"],
        },
        "rdbms": {
            "alembic": {
                "url": "postgresql+psycopg://old:old@old/old",
            },
            "sqlalchemy": {
                "url": "postgresql+psycopg://old:old@old/old",
            },
        },
    }


def _production_config() -> dict:
    config = _base_config()
    config["mugen"]["environment"] = "production"
    config["mugen"]["modules"]["extensions"] = [
        {
            "type": "fw",
            "token": "core.fw.acp",
            "enabled": True,
        }
    ]
    config["acp"].update(
        {
            "secret_key": "prod-acp-bootstrap-secret-0123456789",
            "refresh_token_pepper": "prod-refresh-token-pepper-0123456789",
            "key_management": {
                "providers": {
                    "managed": {
                        "encryption_key": "prod-managed-secret-root-key-0123456789",
                    }
                }
            },
            "jwt": {
                "active_kid": "prod-key",
                "issuer": "mugen",
                "audience": "mugen",
                "keys": [
                    {
                        "kid": "prod-key",
                        "alg": "EdDSA",
                        "pem": (
                            "-----BEGIN PRIVATE KEY-----\n"
                            "not-a-real-test-key\n"
                            "-----END PRIVATE KEY-----\n"
                        ),
                    }
                ],
            },
        }
    )
    return config


class TestMugenDeploymentConfig(unittest.TestCase):
    """Covers deployment config environment overlays."""

    def test_apply_environment_overrides_maps_deployment_variables(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "ENVIRONMENT": "production",
                "APP_NAME": "mugen-api",
                "LOG_LEVEL": "INFO",
                "MUGEN_PLATFORMS": "web, telegram, web",
                "MUGEN_PHASE_B_CRITICAL_PLATFORMS": "web",
                "DATABASE_URL": "postgresql+psycopg://mugen:mugen@db/mugen",
                "SECRET_KEY": "prod-quart-secret-key-0123456789abcdef",
                "CORS_ALLOWED_ORIGINS": (
                    "https://app.example.com, https://admin.example.com"
                ),
                "ACP_SECRET_KEY": "prod-acp-bootstrap-secret-0123456789",
                "ACP_SEED_ACP": "true",
                "ACP_ADMIN_USERNAME": "admin",
                "ACP_ADMIN_LOGIN_EMAIL": "admin@example.com",
                "ACP_ADMIN_PASSWORD": _LOCAL_ADMIN_PASSWORD,
                "ACP_ADMIN_PASSWORD_HASH": _LOCAL_ADMIN_PASSWORD_HASH,
                "ACP_MANAGED_SECRET_ENCRYPTION_KEY": (
                    "prod-managed-secret-root-key-0123456789"
                ),
                "ACP_REFRESH_TOKEN_PEPPER": ("prod-refresh-token-pepper-0123456789"),
                "ACP_JWT_CONFIG_JSON": _jwt_config_json(),
            },
        )

        self.assertEqual(config["mugen"]["environment"], "production")
        self.assertEqual(config["mugen"]["logger"]["name"], "mugen-api")
        self.assertEqual(config["mugen"]["logger"]["level"], 20)
        self.assertEqual(config["mugen"]["platforms"], ["web", "telegram"])
        self.assertEqual(
            config["mugen"]["runtime"]["phase_b"]["critical_platforms"],
            ["web"],
        )
        self.assertEqual(
            config["rdbms"]["alembic"]["url"],
            "postgresql+psycopg://mugen:mugen@db/mugen",
        )
        self.assertEqual(
            config["rdbms"]["sqlalchemy"]["url"],
            "postgresql+psycopg://mugen:mugen@db/mugen",
        )
        self.assertEqual(
            config["acp"]["cors_origins"],
            ["https://app.example.com", "https://admin.example.com"],
        )
        self.assertIs(config["acp"]["seed_acp"], True)
        self.assertEqual(config["acp"]["admin_username"], "admin")
        self.assertEqual(config["acp"]["admin_login_email"], "admin@example.com")
        self.assertEqual(config["acp"]["admin_password"], _LOCAL_ADMIN_PASSWORD)
        self.assertEqual(
            config["acp"]["admin_password_hash"],
            _LOCAL_ADMIN_PASSWORD_HASH,
        )
        self.assertEqual(config["acp"]["jwt"]["active_kid"], "prod-key")
        self.assertEqual(config["acp"]["jwt"]["keys"][0]["kid"], "prod-key")
        self.assertIn(
            "\nnew-not-a-real-test-key\n",
            config["acp"]["jwt"]["keys"][0]["pem"],
        )

    def test_environment_overlay_maps_rotation_ready_jwt_config_json(self) -> None:
        config = _base_config()
        jwt_config = _jwt_config_json(
            active_kid="new-key",
            keys=[
                {
                    "kid": "old-key",
                    "alg": "EdDSA",
                    "pem": _OLD_TEST_PRIVATE_PEM.replace("\n", "\\n"),
                },
                {
                    "kid": "new-key",
                    "alg": "EdDSA",
                    "pem": _NEW_TEST_PRIVATE_PEM.replace("\n", "\\n"),
                },
            ],
        )

        apply_environment_overrides(
            config,
            environ={
                "ACP_JWT_CONFIG_JSON": jwt_config,
            },
        )

        self.assertEqual(config["acp"]["jwt"]["active_kid"], "new-key")
        self.assertEqual(config["acp"]["jwt"]["issuer"], "mugen")
        self.assertEqual(config["acp"]["jwt"]["audience"], "mugen")
        self.assertEqual(
            [entry["kid"] for entry in config["acp"]["jwt"]["keys"]],
            ["old-key", "new-key"],
        )
        self.assertIn(
            "\nold-not-a-real-test-key\n",
            config["acp"]["jwt"]["keys"][0]["pem"],
        )
        self.assertIn(
            "\nnew-not-a-real-test-key\n",
            config["acp"]["jwt"]["keys"][1]["pem"],
        )

    def test_environment_overlay_rejects_invalid_jwt_config_json(self) -> None:
        for raw_value, pattern in (
            ("not-json", "valid JSON"),
            ("[]", "JSON object"),
            (json.dumps({"keys": {}}), "JSON array"),
            (json.dumps({"keys": ["bad"]}), "JSON object"),
        ):
            with self.subTest(raw_value=raw_value):
                with self.assertRaisesRegex(RuntimeError, pattern):
                    apply_environment_overrides(
                        _base_config(),
                        environ={
                            "ACP_JWT_CONFIG_JSON": raw_value,
                        },
                    )

    def test_environment_overlay_accepts_jwt_key_without_pem_string(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "ACP_JWT_CONFIG_JSON": json.dumps(
                    {
                        "active_kid": "kid-1",
                        "issuer": "mugen",
                        "audience": "mugen",
                        "keys": [
                            {
                                "kid": "kid-1",
                                "alg": "EdDSA",
                            }
                        ],
                    }
                ),
            },
        )

        self.assertNotIn("pem", config["acp"]["jwt"]["keys"][0])

    def test_environment_overlay_applies_json_overlay_deep_merge_and_replaces_lists(
        self,
    ) -> None:
        config = _base_config()
        config["mugen"]["platforms"] = ["web"]
        config["openai"] = {
            "api": {
                "key": "old-key",
                "classification": {
                    "model": "old-classifier",
                },
                "completion": {
                    "model": "old-model",
                    "stop": ["old-stop"],
                },
            },
        }

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "platforms": ["web", "telegram"],
                        },
                        "openai": {
                            "api": {
                                "completion": {
                                    "model": "gpt-4.1-mini",
                                    "stop": ["new-stop"],
                                },
                            },
                        },
                        "acme_billing": {
                            "api": {
                                "base_url": "https://billing.example.com",
                            },
                        },
                    }
                ),
            },
        )

        self.assertEqual(config["mugen"]["platforms"], ["web", "telegram"])
        self.assertEqual(config["openai"]["api"]["key"], "old-key")
        self.assertEqual(
            config["openai"]["api"]["classification"]["model"],
            "old-classifier",
        )
        self.assertEqual(
            config["openai"]["api"]["completion"]["model"],
            "gpt-4.1-mini",
        )
        self.assertEqual(config["openai"]["api"]["completion"]["stop"], ["new-stop"])
        self.assertEqual(
            config["acme_billing"]["api"]["base_url"],
            "https://billing.example.com",
        )

    def test_environment_overlay_loads_toml_overlay_file(self) -> None:
        config = _base_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "overlay.toml"
            overlay_path.write_text(
                dedent("""
                    [mugen.modules.core.gateway]
                    completion = "openai"

                    [openai.api.completion]
                    model = "gpt-4.1-mini"
                    temp = 0.1
                    top_p = 0.8
                    """),
                encoding="utf-8",
            )

            apply_environment_overrides(
                config,
                environ={
                    "MUGEN_CONFIG_OVERLAY_FILE": str(overlay_path),
                },
            )

        self.assertEqual(
            config["mugen"]["modules"]["core"]["gateway"]["completion"],
            "openai",
        )
        self.assertEqual(
            config["openai"]["api"]["completion"]["model"],
            "gpt-4.1-mini",
        )
        self.assertEqual(config["openai"]["api"]["completion"]["temp"], 0.1)

    def test_environment_overlay_inline_json_overrides_file_overlay(self) -> None:
        config = _base_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            overlay_path = Path(tmpdir) / "overlay.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "openai": {
                            "api": {
                                "completion": {
                                    "model": "from-file",
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            apply_environment_overrides(
                config,
                environ={
                    "MUGEN_CONFIG_OVERLAY_FILE": str(overlay_path),
                    "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                        {
                            "openai": {
                                "api": {
                                    "completion": {
                                        "model": "from-json",
                                    }
                                }
                            }
                        }
                    ),
                },
            )

        self.assertEqual(
            config["openai"]["api"]["completion"]["model"],
            "from-json",
        )

    def test_environment_overlay_direct_vars_override_generic_overlay(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "logger": {
                                "level": 10,
                            }
                        },
                        "quart": {
                            "secret_key": "overlay-secret-key-0123456789abcdef",
                        },
                        "acp": {
                            "cors_origins": ["https://overlay.example.com"],
                        },
                        "rdbms": {
                            "alembic": {
                                "url": "postgresql+psycopg://overlay@db/mugen",
                            },
                            "sqlalchemy": {
                                "url": "postgresql+psycopg://overlay@db/mugen",
                            },
                        },
                    }
                ),
                "DATABASE_URL": "postgresql+psycopg://direct@db/mugen",
                "SECRET_KEY": "direct-secret-key-0123456789abcdef",
                "LOG_LEVEL": "WARNING",
                "CORS_ALLOWED_ORIGINS": "https://direct.example.com",
            },
        )

        self.assertEqual(
            config["rdbms"]["alembic"]["url"],
            "postgresql+psycopg://direct@db/mugen",
        )
        self.assertEqual(
            config["rdbms"]["sqlalchemy"]["url"],
            "postgresql+psycopg://direct@db/mugen",
        )
        self.assertEqual(
            config["quart"]["secret_key"], "direct-secret-key-0123456789abcdef"
        )
        self.assertEqual(config["mugen"]["logger"]["level"], 30)
        self.assertEqual(config["acp"]["cors_origins"], ["https://direct.example.com"])

    def test_environment_overlay_rejects_invalid_generic_overlay_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            yaml_path = tmp_path / "overlay.yaml"
            yaml_path.write_text("{}", encoding="utf-8")
            invalid_json_path = tmp_path / "invalid.json"
            invalid_json_path.write_text("{", encoding="utf-8")
            invalid_toml_path = tmp_path / "invalid.toml"
            invalid_toml_path.write_text("[broken", encoding="utf-8")
            array_json_path = tmp_path / "array.json"
            array_json_path.write_text("[]", encoding="utf-8")

            cases = (
                (
                    {"MUGEN_CONFIG_OVERLAY_FILE": str(tmp_path / "missing.json")},
                    "does not exist",
                ),
                ({"MUGEN_CONFIG_OVERLAY_FILE": str(tmp_path)}, "must point to a file"),
                ({"MUGEN_CONFIG_OVERLAY_FILE": str(yaml_path)}, ".json or .toml"),
                ({"MUGEN_CONFIG_OVERLAY_FILE": str(invalid_json_path)}, "valid JSON"),
                ({"MUGEN_CONFIG_OVERLAY_FILE": str(invalid_toml_path)}, "valid TOML"),
                ({"MUGEN_CONFIG_OVERLAY_FILE": str(array_json_path)}, "object"),
                ({"MUGEN_CONFIG_OVERLAY_JSON": "not-json"}, "valid JSON"),
                ({"MUGEN_CONFIG_OVERLAY_JSON": "[]"}, "object"),
            )

            for environ, pattern in cases:
                with self.subTest(environ=environ):
                    with self.assertRaisesRegex(RuntimeError, pattern):
                        apply_environment_overrides(_base_config(), environ=environ)

    def test_blank_environment_values_do_not_override_existing_config(self) -> None:
        config = _base_config()
        config["mugen"]["platforms"] = ["web"]
        config["mugen"]["runtime"] = {
            "phase_b": {
                "critical_platforms": ["web"],
            },
        }

        apply_environment_overrides(
            config,
            environ={
                "DATABASE_URL": "   ",
                "LOG_LEVEL": "",
                "CORS_ALLOWED_ORIGINS": " ",
                "MUGEN_PLATFORMS": " ",
                "MUGEN_PHASE_B_CRITICAL_PLATFORMS": "",
            },
        )

        self.assertEqual(
            config["rdbms"]["alembic"]["url"],
            "postgresql+psycopg://old:old@old/old",
        )
        self.assertEqual(config["mugen"]["logger"]["level"], 10)
        self.assertEqual(config["acp"]["cors_origins"], ["*"])
        self.assertEqual(config["mugen"]["platforms"], ["web"])
        self.assertEqual(
            config["mugen"]["runtime"]["phase_b"]["critical_platforms"],
            ["web"],
        )

    def test_environment_overlay_defaults_critical_platforms_to_platforms(
        self,
    ) -> None:
        config = _base_config()
        config["mugen"]["platforms"] = ["web"]
        config["mugen"]["runtime"] = {
            "phase_b": {
                "critical_platforms": ["web"],
            },
        }

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_PLATFORMS": "telegram, web",
            },
        )

        self.assertEqual(config["mugen"]["platforms"], ["telegram", "web"])
        self.assertEqual(
            config["mugen"]["runtime"]["phase_b"]["critical_platforms"],
            ["telegram", "web"],
        )

    def test_environment_overlay_allows_explicit_critical_platform_subset(
        self,
    ) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_PLATFORMS": "web, telegram",
                "MUGEN_PHASE_B_CRITICAL_PLATFORMS": "web",
            },
        )

        self.assertEqual(config["mugen"]["platforms"], ["web", "telegram"])
        self.assertEqual(
            config["mugen"]["runtime"]["phase_b"]["critical_platforms"],
            ["web"],
        )

    def test_environment_overlay_enables_known_builtin_extensions(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_ENABLED_EXTENSIONS": "core.fw.channel_orchestration",
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        self.assertEqual(len(extensions), 1)
        self.assertEqual(extensions[0]["token"], "core.fw.channel_orchestration")
        self.assertIs(extensions[0]["enabled"], True)
        self.assertEqual(
            extensions[0]["models"],
            "mugen.core.plugin.channel_orchestration.model",
        )
        self.assertEqual(extensions[0]["migration_track"], "core")
        self.assertEqual(
            extensions[0]["contrib"],
            "mugen.core.plugin.channel_orchestration.contrib",
        )

    def test_builtin_extension_presets_cover_sample_core_extensions(self) -> None:
        sample_entries = {
            entry["token"]: entry
            for entry in _sample_core_extension_entries()
        }
        presets = deployment_config_module._BUILTIN_EXTENSION_PRESETS

        self.assertFalse(set(sample_entries) - set(presets))
        for token, sample_entry in sample_entries.items():
            with self.subTest(token=token):
                preset = presets[token]
                self.assertEqual(preset["token"], token)
                self.assertEqual(preset["type"], sample_entry["type"])
                self.assertIs(preset["enabled"], True)
                for key in (
                    "name",
                    "namespace",
                    "models",
                    "migration_track",
                    "contrib",
                ):
                    if key in sample_entry:
                        self.assertEqual(preset.get(key), sample_entry[key])

    def test_environment_overlay_enables_all_sample_core_extensions(self) -> None:
        config = _base_config()
        tokens = [
            str(entry["token"])
            for entry in _sample_core_extension_entries()
        ]

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_ENABLED_EXTENSIONS": ",".join(tokens),
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        by_token = {entry["token"]: entry for entry in extensions}
        self.assertEqual(set(by_token), set(tokens))
        self.assertEqual(
            by_token["core.fw.knowledge_pack"]["contrib"],
            "mugen.core.plugin.knowledge_pack.contrib",
        )
        self.assertEqual(by_token["core.ipc.matrix_ingress"]["type"], "ipc")

    def test_environment_overlay_enables_multiple_known_builtin_extensions(
        self,
    ) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_ENABLED_EXTENSIONS": (
                    "core.fw.channel_orchestration,core.fw.audit"
                ),
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        by_token = {entry["token"]: entry for entry in extensions}
        self.assertEqual(
            set(by_token),
            {
                "core.fw.audit",
                "core.fw.channel_orchestration",
            },
        )
        self.assertEqual(
            by_token["core.fw.audit"]["models"],
            "mugen.core.plugin.audit.model",
        )
        self.assertEqual(by_token["core.fw.audit"]["migration_track"], "core")
        self.assertEqual(
            by_token["core.fw.audit"]["contrib"],
            "mugen.core.plugin.audit.contrib",
        )

    def test_environment_overlay_updates_existing_builtin_extensions(self) -> None:
        config = _base_config()
        config["mugen"]["modules"]["extensions"].append(
            {
                "type": "fw",
                "token": "core.fw.channel_orchestration",
                "enabled": False,
                "namespace": "custom.channel.namespace",
            }
        )

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_ENABLED_EXTENSIONS": "core.fw.channel_orchestration",
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        self.assertEqual(len(extensions), 1)
        self.assertIs(extensions[0]["enabled"], True)
        self.assertEqual(
            extensions[0]["namespace"],
            "custom.channel.namespace",
        )
        self.assertEqual(
            extensions[0]["models"],
            "mugen.core.plugin.channel_orchestration.model",
        )

    def test_environment_overlay_enables_predeclared_custom_extensions(
        self,
    ) -> None:
        config = _base_config()
        config["mugen"]["modules"]["extensions"].append(
            {
                "type": "fw",
                "token": "vendor.fw.custom",
                "enabled": False,
                "name": "vendor.custom",
                "namespace": "vendor.custom",
                "models": "vendor.custom.model",
                "migration_track": "vendor",
                "contrib": "vendor.custom.contrib",
            }
        )

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_ENABLED_EXTENSIONS": "vendor.fw.custom",
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        self.assertEqual(len(extensions), 1)
        self.assertIs(extensions[0]["enabled"], True)
        self.assertEqual(extensions[0]["namespace"], "vendor.custom")
        self.assertEqual(extensions[0]["models"], "vendor.custom.model")

    def test_environment_overlay_merges_downstream_extension_json(self) -> None:
        config = _base_config()
        config["mugen"]["modules"]["extensions"].append(
            {
                "type": "fw",
                "token": "vendor.fw.billing",
                "enabled": False,
                "namespace": "old.billing",
            }
        )

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_EXTENSIONS_JSON": json.dumps(
                    [
                        {
                            "type": "fw",
                            "token": "vendor.fw.billing",
                            "enabled": True,
                            "name": "vendor.billing",
                            "namespace": "vendor.billing",
                            "contrib": "vendor.billing.contrib",
                            "models": "vendor.billing.model",
                            "migration_track": "billing",
                        },
                        {
                            "type": "fw",
                            "token": "vendor.fw.audit",
                            "enabled": False,
                            "name": "vendor.audit",
                            "namespace": "vendor.audit",
                            "contrib": "vendor.audit.contrib",
                        },
                    ]
                ),
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        by_token = {entry["token"]: entry for entry in extensions}
        self.assertEqual(set(by_token), {"vendor.fw.audit", "vendor.fw.billing"})
        self.assertIs(by_token["vendor.fw.billing"]["enabled"], True)
        self.assertEqual(by_token["vendor.fw.billing"]["namespace"], "vendor.billing")
        self.assertEqual(
            by_token["vendor.fw.billing"]["models"],
            "vendor.billing.model",
        )
        self.assertIs(by_token["vendor.fw.audit"]["enabled"], False)

    def test_environment_overlay_enables_json_declared_extensions(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_EXTENSIONS_JSON": json.dumps(
                    [
                        {
                            "type": "fw",
                            "token": "vendor.fw.custom",
                            "enabled": False,
                            "name": "vendor.custom",
                            "namespace": "vendor.custom",
                            "contrib": "vendor.custom.contrib",
                            "models": "vendor.custom.model",
                            "migration_track": "vendor",
                        }
                    ]
                ),
                "MUGEN_ENABLED_EXTENSIONS": "vendor.fw.custom",
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        self.assertEqual(len(extensions), 1)
        self.assertIs(extensions[0]["enabled"], True)
        self.assertEqual(extensions[0]["namespace"], "vendor.custom")

    def test_environment_overlay_rejects_invalid_extension_json(self) -> None:
        for raw_value, pattern in (
            ("not-json", "valid JSON"),
            ("{}", "JSON array"),
            (json.dumps(["bad"]), "JSON object"),
            (json.dumps([{"type": "fw"}]), "token"),
        ):
            with self.subTest(raw_value=raw_value):
                with self.assertRaisesRegex(RuntimeError, pattern):
                    apply_environment_overrides(
                        _base_config(),
                        environ={
                            "MUGEN_EXTENSIONS_JSON": raw_value,
                        },
                    )

    def test_environment_overlay_rebuilds_invalid_extension_tables(self) -> None:
        cases = (
            {
                "mugen": "invalid",
            },
            {
                "mugen": {
                    "modules": "invalid",
                },
            },
        )

        for config in cases:
            with self.subTest(config=config):
                apply_environment_overrides(
                    config,
                    environ={
                        "MUGEN_EXTENSIONS_JSON": json.dumps(
                            [
                                {
                                    "type": "fw",
                                    "token": "vendor.fw.custom",
                                    "enabled": True,
                                }
                            ]
                        ),
                    },
                )

                self.assertEqual(
                    config["mugen"]["modules"]["extensions"][0]["token"],
                    "vendor.fw.custom",
                )

    def test_environment_overlay_ignores_unindexable_existing_extensions(
        self,
    ) -> None:
        config = _base_config()
        config["mugen"]["modules"]["extensions"] = [
            123,
            {
                "token": " ",
                "enabled": False,
            },
        ]

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_EXTENSIONS_JSON": json.dumps(
                    [
                        {
                            "type": "fw",
                            "token": "vendor.fw.custom",
                            "enabled": True,
                        }
                    ]
                ),
                "MUGEN_ENABLED_EXTENSIONS": "vendor.fw.custom",
            },
        )

        extensions = config["mugen"]["modules"]["extensions"]
        self.assertEqual(extensions[2]["token"], "vendor.fw.custom")
        self.assertIs(extensions[2]["enabled"], True)

    def test_environment_overlay_merges_downstream_migration_track_json(self) -> None:
        config = _base_config()
        config["rdbms"]["migration_tracks"] = {
            "plugins": [
                {
                    "name": "billing",
                    "enabled": False,
                    "schema": "old_billing",
                }
            ]
        }

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_MIGRATION_TRACKS_JSON": json.dumps(
                    [
                        {
                            "name": "billing",
                            "enabled": True,
                            "alembic_config": "plugins/billing/alembic.ini",
                            "schema": "billing",
                            "version_table": "alembic_version_billing",
                            "version_table_schema": "billing",
                            "model_modules": ["vendor.billing.model"],
                        },
                        {
                            "name": "support",
                            "enabled": True,
                            "schema": "support",
                        },
                    ]
                ),
            },
        )

        tracks = config["rdbms"]["migration_tracks"]["plugins"]
        by_name = {entry["name"]: entry for entry in tracks}
        self.assertEqual(set(by_name), {"billing", "support"})
        self.assertIs(by_name["billing"]["enabled"], True)
        self.assertEqual(by_name["billing"]["schema"], "billing")
        self.assertEqual(
            by_name["billing"]["model_modules"],
            ["vendor.billing.model"],
        )
        self.assertEqual(by_name["support"]["schema"], "support")

    def test_environment_overlay_rejects_invalid_migration_track_json(self) -> None:
        for raw_value, pattern in (
            ("not-json", "valid JSON"),
            ("{}", "JSON array"),
            (json.dumps(["bad"]), "JSON object"),
            (json.dumps([{"enabled": True}]), "name"),
        ):
            with self.subTest(raw_value=raw_value):
                with self.assertRaisesRegex(RuntimeError, pattern):
                    apply_environment_overrides(
                        _base_config(),
                        environ={
                            "MUGEN_MIGRATION_TRACKS_JSON": raw_value,
                        },
                    )

    def test_environment_overlay_rebuilds_invalid_migration_track_tables(
        self,
    ) -> None:
        cases = (
            {
                "rdbms": "invalid",
            },
            {
                "rdbms": {
                    "migration_tracks": "invalid",
                },
            },
        )

        for config in cases:
            with self.subTest(config=config):
                apply_environment_overrides(
                    config,
                    environ={
                        "MUGEN_MIGRATION_TRACKS_JSON": json.dumps(
                            [
                                {
                                    "name": "vendor",
                                    "enabled": True,
                                    "schema": "vendor",
                                }
                            ]
                        ),
                    },
                )

                self.assertEqual(
                    config["rdbms"]["migration_tracks"]["plugins"][0]["name"],
                    "vendor",
                )

    def test_environment_overlay_ignores_unindexable_existing_migration_tracks(
        self,
    ) -> None:
        config = _base_config()
        config["rdbms"]["migration_tracks"] = {
            "plugins": [
                123,
                {
                    "name": " ",
                    "enabled": False,
                },
            ]
        }

        apply_environment_overrides(
            config,
            environ={
                "MUGEN_MIGRATION_TRACKS_JSON": json.dumps(
                    [
                        {
                            "name": "vendor",
                            "enabled": True,
                            "schema": "vendor",
                        }
                    ]
                ),
            },
        )

        tracks = config["rdbms"]["migration_tracks"]["plugins"]
        self.assertEqual(tracks[2]["name"], "vendor")
        self.assertIs(tracks[2]["enabled"], True)

    def test_environment_overlay_rejects_unknown_builtin_extensions(self) -> None:
        config = _base_config()

        with self.assertRaisesRegex(RuntimeError, "unknown extension"):
            apply_environment_overrides(
                config,
                environ={
                    "MUGEN_ENABLED_EXTENSIONS": "core.fw.unknown",
                },
            )

    def test_environment_overlay_generates_local_acp_admin_hash(self) -> None:
        config = _base_config()
        config["acp"].update(
            {
                "seed_acp": True,
                "admin_password_hash": "",
            }
        )

        apply_environment_overrides(
            config,
            environ={
                "ACP_ADMIN_PASSWORD": _LOCAL_ADMIN_PASSWORD,
            },
        )

        self.assertNotEqual(
            config["acp"]["admin_password_hash"],
            "",
        )
        self.assertTrue(
            check_password_hash(
                config["acp"]["admin_password_hash"],
                _LOCAL_ADMIN_PASSWORD,
            )
        )

    def test_environment_overlay_keeps_explicit_acp_admin_hash(self) -> None:
        config = _base_config()
        config["acp"].update(
            {
                "seed_acp": True,
                "admin_password_hash": "",
            }
        )

        apply_environment_overrides(
            config,
            environ={
                "ACP_ADMIN_PASSWORD": _LOCAL_ADMIN_PASSWORD,
                "ACP_ADMIN_PASSWORD_HASH": _LOCAL_ADMIN_PASSWORD_HASH,
            },
        )

        self.assertEqual(
            config["acp"]["admin_password_hash"],
            _LOCAL_ADMIN_PASSWORD_HASH,
        )

    def test_environment_overlay_keeps_existing_acp_admin_hash(self) -> None:
        config = _base_config()
        config["acp"].update(
            {
                "seed_acp": True,
                "admin_password_hash": _LOCAL_ADMIN_PASSWORD_HASH,
            }
        )

        apply_environment_overrides(
            config,
            environ={
                "ACP_ADMIN_PASSWORD": _LOCAL_ADMIN_PASSWORD,
            },
        )

        self.assertEqual(
            config["acp"]["admin_password_hash"],
            _LOCAL_ADMIN_PASSWORD_HASH,
        )

    def test_environment_overlay_generates_local_jwt_key_for_development(
        self,
    ) -> None:
        config = _base_config()
        config["acp"]["jwt"] = {
            "active_kid": "<kid>",
            "issuer": "<issuer>",
            "audience": "<audience>",
            "keys": [
                {
                    "kid": "<kid>",
                    "alg": "EdDSA",
                    "pem": (
                        "-----BEGIN PRIVATE KEY-----\n"
                        "<replace-with-private-key>\n"
                        "-----END PRIVATE KEY-----\n"
                    ),
                }
            ],
        }

        apply_environment_overrides(
            config,
            environ={
                "ACP_JWT_ACTIVE_KID": "local-dev-ed25519",
            },
        )

        pem = config["acp"]["jwt"]["keys"][0]["pem"]
        private_key = serialization.load_pem_private_key(
            pem.encode("utf-8"),
            password=None,
        )
        self.assertIsInstance(private_key, ed25519.Ed25519PrivateKey)
        self.assertEqual(config["acp"]["jwt"]["active_kid"], "local-dev-ed25519")
        self.assertEqual(config["acp"]["jwt"]["keys"][0]["kid"], "local-dev-ed25519")

    def test_environment_overlay_keeps_existing_local_jwt_key_for_development(
        self,
    ) -> None:
        pem = _real_ed25519_private_pem()
        config = _base_config()
        config["acp"]["jwt"] = {
            "active_kid": "old-kid",
            "issuer": "mugen-local",
            "audience": "mugen-local",
            "keys": [
                {
                    "kid": "old-kid",
                    "alg": "EdDSA",
                    "pem": pem,
                }
            ],
        }

        apply_environment_overrides(
            config,
            environ={
                "ACP_JWT_ACTIVE_KID": "local-dev-ed25519",
            },
        )

        self.assertEqual(config["acp"]["jwt"]["keys"][0]["pem"], pem)
        self.assertEqual(config["acp"]["jwt"]["keys"][0]["kid"], "local-dev-ed25519")

    def test_environment_overlay_does_not_generate_jwt_key_for_production(
        self,
    ) -> None:
        config = _base_config()
        config["mugen"]["environment"] = "production"
        config["acp"]["jwt"] = {
            "active_kid": "<kid>",
            "issuer": "<issuer>",
            "audience": "<audience>",
            "keys": [
                {
                    "kid": "<kid>",
                    "alg": "EdDSA",
                    "pem": (
                        "-----BEGIN PRIVATE KEY-----\n"
                        "<replace-with-private-key>\n"
                        "-----END PRIVATE KEY-----\n"
                    ),
                }
            ],
        }

        apply_environment_overrides(
            config,
            environ={
                "ACP_JWT_ACTIVE_KID": "prod-ed25519",
            },
        )

        self.assertIn(
            "<replace-with-private-key>",
            config["acp"]["jwt"]["keys"][0]["pem"],
        )

    def test_environment_overlay_rebuilds_missing_nested_tables(self) -> None:
        config = {
            "mugen": "invalid",
            "acp": "invalid",
        }

        apply_environment_overrides(
            config,
            environ={
                "ENVIRONMENT": "production",
                "MUGEN_PLATFORMS": "web",
                "MUGEN_PHASE_B_CRITICAL_PLATFORMS": "web",
                "ACP_JWT_ACTIVE_KID": "kid-1",
            },
        )

        self.assertEqual(config["mugen"]["environment"], "production")
        self.assertEqual(config["mugen"]["platforms"], ["web"])
        self.assertEqual(
            config["mugen"]["runtime"]["phase_b"]["critical_platforms"],
            ["web"],
        )
        self.assertEqual(config["acp"]["jwt"]["active_kid"], "kid-1")
        self.assertEqual(config["acp"]["jwt"]["keys"][0]["kid"], "kid-1")
        self.assertEqual(config["acp"]["jwt"]["keys"][0]["alg"], "EdDSA")

    def test_environment_overlay_rebuilds_invalid_jwt_shapes(self) -> None:
        for config in (
            {
                "acp": "invalid",
            },
            {
                "acp": {
                    "jwt": "invalid",
                },
            },
        ):
            with self.subTest(config=config):
                apply_environment_overrides(
                    config,
                    environ={
                        "ACP_JWT_CONFIG_JSON": _jwt_config_json(),
                    },
                )

                self.assertEqual(config["acp"]["jwt"]["active_kid"], "prod-key")
                self.assertIn(
                    "BEGIN PRIVATE KEY",
                    config["acp"]["jwt"]["keys"][0]["pem"],
                )

        config = {
            "acp": {
                "jwt": {
                    "keys": ["invalid"],
                },
            },
        }
        apply_environment_overrides(
            config,
            environ={
                "ACP_JWT_ACTIVE_KID": "kid-2",
            },
        )
        self.assertEqual(config["acp"]["jwt"]["keys"][0]["kid"], "kid-2")

    def test_environment_overlay_ignores_non_string_values(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "ENVIRONMENT": 123,
            },
        )

        self.assertEqual(config["mugen"]["environment"], "development")

    def test_environment_overlay_rejects_non_dict_config(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be a dict"):
            apply_environment_overrides([])  # type: ignore[arg-type]

    def test_cors_overlay_deduplicates_and_drops_empty_items(self) -> None:
        config = _base_config()

        apply_environment_overrides(
            config,
            environ={
                "CORS_ALLOWED_ORIGINS": (
                    "https://app.example.com,,https://app.example.com,"
                    "https://admin.example.com"
                ),
            },
        )

        self.assertEqual(
            config["acp"]["cors_origins"],
            ["https://app.example.com", "https://admin.example.com"],
        )

    def test_bool_overlay_accepts_common_values(self) -> None:
        for raw_value, expected in (
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
        ):
            with self.subTest(raw_value=raw_value):
                config = _base_config()
                apply_environment_overrides(
                    config,
                    environ={"ACP_SEED_ACP": raw_value},
                )
                self.assertIs(config["acp"]["seed_acp"], expected)

    def test_bool_overlay_rejects_invalid_value(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ACP_SEED_ACP"):
            apply_environment_overrides(
                _base_config(),
                environ={"ACP_SEED_ACP": "maybe"},
            )

    def test_parse_log_level_accepts_names_and_numbers(self) -> None:
        self.assertEqual(parse_log_level("INFO"), 20)
        self.assertEqual(parse_log_level("15"), 15)
        self.assertEqual(parse_log_level(30), 30)
        with self.assertRaisesRegex(RuntimeError, "LOG_LEVEL"):
            parse_log_level("definitely-not-a-level")

    def test_parse_log_level_rejects_invalid_values(self) -> None:
        for value in (False, -1, object(), " ", "-1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "LOG_LEVEL"):
                    parse_log_level(value)

    def test_non_production_validation_is_noop_for_missing_or_invalid_environment(
        self,
    ) -> None:
        validate_production_deployment_config({"mugen": {"environment": 123}})
        validate_production_deployment_config({"mugen": {"environment": "development"}})

    def test_production_validation_rejects_missing_database_url(self) -> None:
        config = _production_config()
        config["rdbms"] = "invalid"

        with self.assertRaisesRegex(RuntimeError, "rdbms.alembic.url"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_sample_database_url(self) -> None:
        config = _production_config()
        config["rdbms"]["alembic"][
            "url"
        ] = "postgresql+psycopg://user:password@server/database"

        with self.assertRaisesRegex(RuntimeError, "sample values"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_wildcard_cors(self) -> None:
        config = _production_config()

        with self.assertRaisesRegex(RuntimeError, "cors_origins"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_missing_cors(self) -> None:
        for origins in ("*", []):
            config = _production_config()
            config["acp"]["cors_origins"] = origins

            with self.subTest(origins=origins):
                with self.assertRaisesRegex(RuntimeError, "cors_origins"):
                    validate_production_deployment_config(config)

    def test_production_validation_skips_acp_when_extension_is_absent_or_disabled(
        self,
    ) -> None:
        for extensions in (
            {},
            [123, {"token": "other.fw.plugin"}],
            [{"token": "core.fw.acp", "enabled": "false"}],
        ):
            config = _production_config()
            config["mugen"]["modules"]["extensions"] = extensions

            with self.subTest(extensions=extensions):
                validate_production_deployment_config(config)

    def test_production_validation_rejects_placeholder_acp_secret(self) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["secret_key"] = "<set-acp-secret-key>"

        with self.assertRaisesRegex(RuntimeError, "placeholder"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_missing_acp_secret_fields(self) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["refresh_token_pepper"] = ""

        with self.assertRaisesRegex(RuntimeError, "refresh_token_pepper"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_invalid_jwt_keys(self) -> None:
        cases = []

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["keys"] = []
        cases.append((config, "keys\\[0\\]"))

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["keys"][0]["alg"] = "HS256"
        cases.append((config, "EdDSA"))

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["keys"][0]["pem"] = "not-a-pem"
        cases.append((config, "private PEM"))

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["active_kid"] = "missing-key"
        cases.append((config, "active_kid"))

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["keys"].append(
            {
                "kid": "prod-key",
                "alg": "EdDSA",
                "pem": _OLD_TEST_PRIVATE_PEM,
            }
        )
        cases.append((config, "unique"))

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["keys"].append("bad")
        cases.append((config, "keys\\[1\\]"))

        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"]["jwt"]["keys"].append(
            {
                "kid": "old-key",
                "alg": "HS256",
                "pem": _OLD_TEST_PRIVATE_PEM,
            }
        )
        cases.append((config, "keys\\[1\\].alg"))

        for config, pattern in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(RuntimeError, pattern):
                    validate_production_deployment_config(config)

    def test_production_validation_accepts_resolved_config(self) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]

        validate_production_deployment_config(config)

    def test_production_validation_allows_unused_gateway_placeholders(self) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["mugen"]["modules"]["core"] = {
            "gateway": {
                "completion": "deterministic",
            }
        }
        config["openai"] = {
            "api": {
                "key": "<openai-api-key>",
            }
        }

        validate_production_deployment_config(config)

    def test_production_validation_rejects_selected_gateway_placeholders(
        self,
    ) -> None:
        cases = (
            (
                {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "completion": "openai",
                                }
                            }
                        }
                    },
                    "openai": {
                        "api": {
                            "key": "<openai-api-key>",
                        }
                    },
                },
                "openai.api.key",
            ),
            (
                {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "completion": "bedrock",
                                }
                            }
                        }
                    },
                    "aws": {
                        "bedrock": {
                            "api": {
                                "access_key_id": "<aws-access-key-id>",
                                "secret_access_key": "<aws-secret-access-key>",
                            }
                        }
                    },
                },
                "aws.bedrock.api.access_key_id",
            ),
            (
                {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "knowledge": "pinecone",
                                }
                            }
                        }
                    },
                    "pinecone": {
                        "api": {
                            "key": "<pinecone-api-key>",
                        }
                    },
                },
                "pinecone.api.key",
            ),
            (
                {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "sms": "twilio",
                                }
                            }
                        }
                    },
                    "twilio": {
                        "api": {
                            "account_sid": "<twilio-account-sid>",
                            "auth_token": "<twilio-auth-token>",
                        }
                    },
                },
                "twilio.api.account_sid",
            ),
        )

        for overlay, pattern in cases:
            with self.subTest(pattern=pattern):
                config = _production_config()
                config["acp"]["cors_origins"] = ["https://app.example.com"]
                apply_environment_overrides(
                    config,
                    environ={
                        "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(overlay),
                    },
                )

                with self.assertRaisesRegex(RuntimeError, pattern):
                    validate_production_deployment_config(config)

    def test_production_validation_accepts_selected_gateway_credentials(self) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "modules": {
                                "core": {
                                    "gateway": {
                                        "completion": "openai",
                                        "email": "smtp",
                                        "knowledge": "qdrant",
                                        "sms": "twilio",
                                    }
                                }
                            }
                        },
                        "openai": {
                            "api": {
                                "key": "prod-openai-key",
                            }
                        },
                        "smtp": {
                            "username": "smtp-user",
                            "password": "smtp-password",
                        },
                        "qdrant": {
                            "api": {
                                "key": "",
                            }
                        },
                        "twilio": {
                            "api": {
                                "account_sid": "prod-twilio-account",
                                "auth_token": "prod-twilio-token",
                                "api_key_sid": "",
                                "api_key_secret": "",
                            }
                        },
                    }
                ),
            },
        )

        validate_production_deployment_config(config)

    def test_production_validation_accepts_task_role_gateway_modes(self) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "modules": {
                                "core": {
                                    "gateway": {
                                        "completion": "bedrock",
                                        "email": "ses",
                                        "knowledge": "pinecone",
                                    }
                                }
                            }
                        },
                        "pinecone": {
                            "api": {
                                "key": "prod-pinecone-key",
                            }
                        },
                    }
                ),
            },
        )

        validate_production_deployment_config(config)

    def test_production_validation_accepts_vertex_access_token_when_selected(
        self,
    ) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "modules": {
                                "core": {
                                    "gateway": {
                                        "completion": "vertex",
                                    }
                                }
                            }
                        },
                        "gcp": {
                            "vertex": {
                                "api": {
                                    "access_token": "prod-vertex-token",
                                }
                            }
                        },
                    }
                ),
            },
        )

        validate_production_deployment_config(config)

    def test_production_validation_rejects_optional_gateway_pair_mismatch(
        self,
    ) -> None:
        cases = (
            (
                {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "completion": "bedrock",
                                }
                            }
                        }
                    },
                    "aws": {
                        "bedrock": {
                            "api": {
                                "access_key_id": "prod-access-key",
                            }
                        }
                    },
                },
                "aws.bedrock.api.access_key_id",
            ),
            (
                {
                    "mugen": {
                        "modules": {
                            "core": {
                                "gateway": {
                                    "email": "smtp",
                                }
                            }
                        }
                    },
                    "smtp": {
                        "username": "smtp-user",
                    },
                },
                "smtp.username",
            ),
        )

        for overlay, pattern in cases:
            with self.subTest(pattern=pattern):
                config = _production_config()
                config["acp"]["cors_origins"] = ["https://app.example.com"]
                apply_environment_overrides(
                    config,
                    environ={
                        "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(overlay),
                    },
                )

                with self.assertRaisesRegex(RuntimeError, pattern):
                    validate_production_deployment_config(config)

    def test_production_validation_rejects_ses_session_token_without_keys(
        self,
    ) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "modules": {
                                "core": {
                                    "gateway": {
                                        "email": "ses",
                                    }
                                }
                            }
                        },
                        "aws": {
                            "ses": {
                                "api": {
                                    "session_token": "prod-session-token",
                                }
                            }
                        },
                    }
                ),
            },
        )

        with self.assertRaisesRegex(RuntimeError, "session_token"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_twilio_auth_mode_errors(self) -> None:
        cases = (
            (
                {
                    "account_sid": "prod-twilio-account",
                },
                "exactly one auth mode",
            ),
            (
                {
                    "account_sid": "prod-twilio-account",
                    "auth_token": "prod-twilio-token",
                    "api_key_sid": "prod-twilio-api-key",
                    "api_key_secret": "prod-twilio-api-secret",
                },
                "exactly one auth mode",
            ),
            (
                {
                    "account_sid": "prod-twilio-account",
                    "api_key_sid": "prod-twilio-api-key",
                },
                "twilio.api.api_key_sid",
            ),
        )

        for twilio_api, pattern in cases:
            with self.subTest(pattern=pattern):
                config = _production_config()
                config["acp"]["cors_origins"] = ["https://app.example.com"]
                apply_environment_overrides(
                    config,
                    environ={
                        "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                            {
                                "mugen": {
                                    "modules": {
                                        "core": {
                                            "gateway": {
                                                "sms": "twilio",
                                            }
                                        }
                                    }
                                },
                                "twilio": {
                                    "api": twilio_api,
                                },
                            }
                        ),
                    },
                )

                with self.assertRaisesRegex(RuntimeError, pattern):
                    validate_production_deployment_config(config)

    def test_production_validation_rejects_vertex_placeholder_when_selected(
        self,
    ) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        apply_environment_overrides(
            config,
            environ={
                "MUGEN_CONFIG_OVERLAY_JSON": json.dumps(
                    {
                        "mugen": {
                            "modules": {
                                "core": {
                                    "gateway": {
                                        "completion": "vertex",
                                    }
                                }
                            }
                        },
                        "gcp": {
                            "vertex": {
                                "api": {
                                    "access_token": "<vertex-access-token>",
                                }
                            }
                        },
                    }
                ),
            },
        )

        with self.assertRaisesRegex(RuntimeError, "gcp.vertex.api.access_token"):
            validate_production_deployment_config(config)

    def test_production_validation_rejects_mismatched_acp_admin_password_hash(
        self,
    ) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"].update(
            {
                "seed_acp": True,
                "admin_username": "admin",
                "admin_login_email": "admin@example.com",
                "admin_password": _LOCAL_ADMIN_PASSWORD,
                "admin_password_hash": (
                    "scrypt:32768:8:1$Hwq89E662mEFoypg$" "not-the-right-hash"
                ),
            }
        )

        with self.assertRaisesRegex(RuntimeError, "admin_password_hash"):
            validate_production_deployment_config(config)

    def test_production_validation_accepts_matching_acp_admin_password_hash(
        self,
    ) -> None:
        config = _production_config()
        config["acp"]["cors_origins"] = ["https://app.example.com"]
        config["acp"].update(
            {
                "seed_acp": True,
                "admin_username": "admin",
                "admin_login_email": "admin@example.com",
                "admin_password": _LOCAL_ADMIN_PASSWORD,
                "admin_password_hash": _LOCAL_ADMIN_PASSWORD_HASH,
            }
        )

        validate_production_deployment_config(config)

    def test_app_and_migration_config_loaders_apply_same_overlay(self) -> None:
        toml_text = dedent("""
            [mugen]
            environment = "development"

            [mugen.logger]
            level = 10
            name = "COM.VORSOCOMPUTING.MUGEN"

            [quart]
            secret_key = "0123456789abcdef0123456789abcdef"

            [acp]
            cors_origins = ["*"]

            [rdbms.alembic]
            url = "postgresql+psycopg://old:old@old/old"

            [rdbms.sqlalchemy]
            url = "postgresql+psycopg://old:old@old/old"
            """)
        env = {
            "DATABASE_URL": "postgresql+psycopg://mugen:mugen@db/mugen",
            "LOG_LEVEL": "WARNING",
            "CORS_ALLOWED_ORIGINS": "https://app.example.com",
            "MUGEN_PLATFORMS": "web,telegram",
            "MUGEN_PHASE_B_CRITICAL_PLATFORMS": "web",
            "MUGEN_EXTENSIONS_JSON": json.dumps(
                [
                    {
                        "type": "fw",
                        "token": "vendor.fw.custom",
                        "enabled": False,
                        "name": "vendor.custom",
                        "namespace": "vendor.custom",
                        "contrib": "vendor.custom.contrib",
                        "models": "vendor.custom.model",
                        "migration_track": "vendor",
                    }
                ]
            ),
            "MUGEN_ENABLED_EXTENSIONS": "vendor.fw.custom",
            "MUGEN_MIGRATION_TRACKS_JSON": json.dumps(
                [
                    {
                        "name": "vendor",
                        "enabled": True,
                        "alembic_config": "plugins/vendor/alembic.ini",
                        "schema": "vendor",
                        "version_table": "alembic_version_vendor",
                        "version_table_schema": "vendor",
                        "model_modules": ["vendor.custom.model"],
                    }
                ]
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "mugen.container.toml"
            path.write_text(toml_text, encoding="utf-8")
            overlay_path = Path(tmpdir) / "overlay.json"
            overlay_path.write_text(
                json.dumps(
                    {
                        "mugen": {
                            "modules": {
                                "core": {
                                    "gateway": {
                                        "completion": "deterministic",
                                    }
                                }
                            }
                        },
                        "openai": {
                            "api": {
                                "completion": {
                                    "model": "from-file",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            env["MUGEN_CONFIG_OVERLAY_FILE"] = str(overlay_path)
            env["MUGEN_CONFIG_OVERLAY_JSON"] = json.dumps(
                {
                    "openai": {
                        "api": {
                            "completion": {
                                "model": "from-json",
                            }
                        }
                    },
                    "acme_billing": {
                        "api": {
                            "base_url": "https://billing.example.com",
                        }
                    },
                }
            )

            with patch.dict("os.environ", env, clear=True):
                app_config = di._load_config(
                    str(path)
                )  # pylint: disable=protected-access
                migration_config = load_mugen_config(path)

        for config in (app_config, migration_config):
            self.assertEqual(
                config["rdbms"]["alembic"]["url"],
                "postgresql+psycopg://mugen:mugen@db/mugen",
            )
            self.assertEqual(config["mugen"]["logger"]["level"], 30)
            self.assertEqual(config["mugen"]["platforms"], ["web", "telegram"])
            self.assertEqual(
                config["mugen"]["runtime"]["phase_b"]["critical_platforms"],
                ["web"],
            )
            self.assertEqual(config["acp"]["cors_origins"], ["https://app.example.com"])
            self.assertEqual(
                config["openai"]["api"]["completion"]["model"],
                "from-json",
            )
            self.assertEqual(
                config["acme_billing"]["api"]["base_url"],
                "https://billing.example.com",
            )
            extensions = config["mugen"]["modules"]["extensions"]
            self.assertEqual(extensions[0]["token"], "vendor.fw.custom")
            self.assertIs(extensions[0]["enabled"], True)
            plugin_tracks = config["rdbms"]["migration_tracks"]["plugins"]
            self.assertEqual(plugin_tracks[0]["name"], "vendor")
            self.assertEqual(plugin_tracks[0]["model_modules"], ["vendor.custom.model"])
