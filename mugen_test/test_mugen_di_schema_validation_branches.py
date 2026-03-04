"""Additional branch coverage tests for strict DI schema validation."""

from __future__ import annotations

import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core import di


def _valid_core_config() -> dict:
    return {
        "rdbms": {
            "migration_tracks": {
                "core": {
                    "schema": "mugen",
                }
            }
        },
        "mugen": {
            "runtime": {
                "profile": "platform_full",
                "provider_readiness_timeout_seconds": 15.0,
                "provider_shutdown_timeout_seconds": 10.0,
                "shutdown_timeout_seconds": 60.0,
                "phase_b": {
                    "startup_timeout_seconds": 30.0,
                    "readiness_grace_seconds": 0.0,
                    "critical_platforms": [],
                    "degrade_on_critical_exit": True,
                },
            },
            "messaging": {
                "mh_mode": "optional",
            },
            "modules": {
                "core": {
                    "client": {
                        "matrix": "default",
                        "whatsapp": "default",
                        "web": "default",
                    },
                    "gateway": {
                        "completion": "deterministic",
                        "logging": "standard",
                        "storage": {
                            "keyval": "relational",
                            "media": "default",
                            "relational": "sqlalchemy",
                            "web_runtime": "relational",
                        },
                    },
                    "service": {
                        "ipc": "default",
                        "messaging": "default",
                        "nlp": "default",
                        "platform": "default",
                        "user": "default",
                    },
                    "extensions": [],
                },
                "extensions": [],
            },
            "platforms": [],
        },
        "matrix": {
            "homeserver": "https://matrix.example.com",
            "client": {
                "user": "@assistant:example.com",
                "password": "matrix-password",
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
                "max_download_bytes": 20971520,
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


class TestDISchemaValidationBranches(unittest.TestCase):
    """Exercise strict schema failure branches added for tokenized DI."""

    def test_core_schema_rejects_invalid_shapes_and_tokens(self) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_core_config()
        cfg["mugen"]["unexpected"] = True
        cases.append((cfg, "unknown key(s) at mugen"))

        cfg = _valid_core_config()
        del cfg["rdbms"]["migration_tracks"]["core"]["schema"]
        cases.append((cfg, "rdbms.migration_tracks.core.schema is required"))

        cfg = _valid_core_config()
        cfg["mugen"] = None
        cases.append((cfg, "[mugen] section is required"))

        cfg = _valid_core_config()
        cfg["mugen"]["runtime"] = None
        cases.append((cfg, "mugen.runtime must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["runtime"]["phase_b"] = None
        cases.append((cfg, "mugen.runtime.phase_b must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["messaging"] = None
        cases.append((cfg, "mugen.messaging must be a table"))

        cfg = _valid_core_config()
        del cfg["mugen"]["messaging"]["mh_mode"]
        cases.append((cfg, "mugen.messaging.mh_mode is required"))

        cfg = _valid_core_config()
        cfg["mugen"]["messaging"]["mh_mode"] = "invalid"
        cases.append((cfg, "mugen.messaging.mh_mode is required"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"] = []
        cases.append((cfg, "mugen.modules must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"] = []
        cases.append((cfg, "mugen.modules.core must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["client"] = []
        cases.append((cfg, "mugen.modules.core.client must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["client"]["matrix"] = None
        cases.append((cfg, "client.matrix must be a token string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["client"]["matrix"] = "mod:Cls"
        cases.append((cfg, "module:Class unsupported"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"] = []
        cases.append((cfg, "mugen.modules.core.gateway must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["storage"] = []
        cases.append((cfg, "gateway.storage must be a table"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["completion"] = ""
        cases.append((cfg, "gateway.completion must be a token string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["completion"] = "mod:Cls"
        cases.append((cfg, "gateway.completion must be a token"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["storage"]["keyval"] = ""
        cases.append((cfg, "storage.keyval must be a token string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["storage"]["keyval"] = "mod:Cls"
        cases.append((cfg, "storage.keyval must be a token"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["email"] = ""
        cases.append((cfg, "gateway.email must be a token string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["email"] = "mod:Cls"
        cases.append((cfg, "gateway.email must be a token"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["extensions"] = {}
        cases.append((cfg, "core.extensions must be an array"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["extensions"] = [123]
        cases.append((cfg, "entries must be tables"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["extensions"] = [{"type": "cp"}]
        cases.append((cfg, ".token is required and must be a string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["extensions"] = [
            {"type": "cp", "token": "mod:Cls"}
        ]
        cases.append((cfg, ".token must be a token"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["extensions"] = [{"type": 123, "token": "t"}]
        cases.append((cfg, ".type must be a string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["extensions"] = {}
        cases.append((cfg, "modules.extensions must be an array"))

        for candidate, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, re.escape(message)):
                    di._validate_core_module_schema(candidate)

    def test_core_schema_handles_none_core_and_extension_lists(self) -> None:
        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["extensions"] = None
        cfg["mugen"]["modules"]["extensions"] = None
        di._validate_core_module_schema(cfg)

    def test_core_schema_accepts_optional_gateway_tokens_and_extensions(self) -> None:
        for knowledge_token in ("qdrant", "chromadb", "milvus", "pgvector", "pinecone"):
            cfg = _valid_core_config()
            cfg["mugen"]["modules"]["core"]["gateway"]["email"] = "smtp"
            cfg["mugen"]["modules"]["core"]["gateway"]["knowledge"] = knowledge_token
            cfg["mugen"]["modules"]["extensions"] = [
                {
                    "type": "cp",
                    "token": "core.cp.clear_history",
                }
            ]
            di._validate_core_module_schema(cfg)

    def test_core_schema_validates_required_runtime_shutdown_timeouts(self) -> None:
        cfg = _valid_core_config()
        cfg["mugen"]["runtime"]["provider_shutdown_timeout_seconds"] = 10.0
        cfg["mugen"]["runtime"]["shutdown_timeout_seconds"] = 60.0
        di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        del cfg["mugen"]["runtime"]["provider_shutdown_timeout_seconds"]
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.provider_shutdown_timeout_seconds is required",
        ):
            di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        del cfg["mugen"]["runtime"]["shutdown_timeout_seconds"]
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.shutdown_timeout_seconds is required",
        ):
            di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        cfg["mugen"]["runtime"]["provider_shutdown_timeout_seconds"] = "bad"
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.provider_shutdown_timeout_seconds must be a positive finite number",
        ):
            di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        cfg["mugen"]["runtime"]["shutdown_timeout_seconds"] = 0
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.shutdown_timeout_seconds must be greater than 0",
        ):
            di._validate_core_module_schema(cfg)

    def test_core_schema_validates_required_runtime_profile_and_startup_controls(
        self,
    ) -> None:
        cfg = _valid_core_config()
        di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        del cfg["mugen"]["runtime"]["profile"]
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.profile is required and must be platform_full",
        ):
            di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        cfg["mugen"]["runtime"]["profile"] = "legacy"
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.profile must be platform_full",
        ):
            di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        del cfg["mugen"]["runtime"]["provider_readiness_timeout_seconds"]
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.provider_readiness_timeout_seconds is required",
        ):
            di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        del cfg["mugen"]["runtime"]["phase_b"]["startup_timeout_seconds"]
        with self.assertRaisesRegex(
            RuntimeError,
            "mugen.runtime.phase_b.startup_timeout_seconds is required",
        ):
            di._validate_core_module_schema(cfg)

    def test_core_schema_requires_matrix_encryption_key_when_matrix_enabled(
        self,
    ) -> None:
        for mutate in (
            lambda cfg: cfg.update({"security": "invalid-shape"}),
            lambda cfg: cfg.update({"security": {}}),
            lambda cfg: cfg.update({"security": {"secrets": {}}}),
            lambda cfg: cfg.update(
                {"security": {"secrets": {"encryption_key": "   "}}}
            ),
        ):
            cfg = _valid_core_config()
            cfg["mugen"]["platforms"] = ["matrix"]
            mutate(cfg)
            with self.subTest(security=cfg.get("security")):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "security.secrets.encryption_key",
                ):
                    di._validate_core_module_schema(cfg)

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        di._validate_core_module_schema(cfg)

    def test_core_schema_requires_strict_matrix_runtime_contract_when_enabled(
        self,
    ) -> None:
        cases: list[tuple[dict, str]] = []

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["homeserver"] = ""
        cases.append((cfg, "matrix.homeserver"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["client"]["user"] = ""
        cases.append((cfg, "matrix.client.user"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["client"]["password"] = ""
        cases.append((cfg, "matrix.client.password"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["domains"]["allowed"] = []
        cases.append((cfg, "matrix.domains.allowed"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["domains"]["denied"] = "example.com"
        cases.append((cfg, "matrix.domains.denied"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["invites"]["direct_only"] = "true"
        cases.append((cfg, "matrix.invites.direct_only"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["media"]["allowed_mimetypes"] = []
        cases.append((cfg, "matrix.media.allowed_mimetypes"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["media"]["max_download_bytes"] = 0
        cases.append((cfg, "matrix.media.max_download_bytes"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["security"]["device_trust"]["mode"] = "invalid"
        cases.append((cfg, "matrix.security.device_trust.mode"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = []
        cases.append((cfg, "matrix.security.device_trust.allowlist"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "   ",
                "device_ids": ["DEV-1"],
            }
        ]
        cases.append((cfg, "matrix.security.device_trust.allowlist[0].user_id"))

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "@user:example.com",
                "device_ids": [],
            }
        ]
        cases.append((cfg, "matrix.security.device_trust.allowlist[0].device_ids"))

        for candidate, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, re.escape(message)):
                    di._validate_core_module_schema(candidate)

        cfg = _valid_core_config()
        cfg["mugen"]["platforms"] = ["matrix"]
        cfg["matrix"]["security"]["device_trust"]["mode"] = "allowlist"
        cfg["matrix"]["security"]["device_trust"]["allowlist"] = [
            {
                "user_id": "@user:example.com",
                "device_ids": ["DEV-1"],
            }
        ]
        di._validate_core_module_schema(cfg)

    def test_build_provider_logs_relational_runtime_bootstrap_failure(self) -> None:
        config = _valid_core_config()
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )

        class _DummyKeyval:  # pylint: disable=too-few-public-methods
            def __init__(
                self, config, logging_gateway, relational_runtime
            ):  # noqa: ANN001
                _ = (config, logging_gateway, relational_runtime)

        with (
            patch(
                "mugen.core.di.resolve_provider_class",
                return_value=_DummyKeyval,
            ),
            patch(
                "mugen.core.di._build_shared_relational_runtime",
                side_effect=RuntimeError("runtime failed"),
            ),
        ):
            di._build_provider(config, injector, provider_name="keyval_storage_gateway")

        self.assertIsNone(injector.keyval_storage_gateway)

    def test_build_provider_raises_relational_runtime_bootstrap_failure_strict(
        self,
    ) -> None:
        config = _valid_core_config()
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )

        class _DummyKeyval:  # pylint: disable=too-few-public-methods
            def __init__(
                self, config, logging_gateway, relational_runtime
            ):  # noqa: ANN001
                _ = (config, logging_gateway, relational_runtime)

        with (
            patch(
                "mugen.core.di.resolve_provider_class",
                return_value=_DummyKeyval,
            ),
            patch(
                "mugen.core.di._build_shared_relational_runtime",
                side_effect=RuntimeError("runtime failed"),
            ),
            self.assertRaises(di.ProviderBootstrapError) as raised,
        ):
            di._build_provider(
                config,
                injector,
                provider_name="keyval_storage_gateway",
                strict_required=True,
            )

        self.assertIn(
            "Provider bootstrap failed (keyval_storage_gateway)", str(raised.exception)
        )
