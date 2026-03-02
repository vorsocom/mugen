"""Additional branch coverage tests for strict DI schema validation."""

from __future__ import annotations

import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mugen.core import di


def _valid_core_config() -> dict:
    return {
        "mugen": {
            "runtime": {
                "profile": "api_only",
                "provider_readiness_timeout_seconds": 15.0,
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
                    "plugins": [],
                },
                "extensions": [],
            },
            "platforms": [],
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
        cfg["mugen"]["modules"]["core"]["plugins"] = {}
        cases.append((cfg, "core.plugins must be an array"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["plugins"] = [123]
        cases.append((cfg, "entries must be tables"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["plugins"] = [{"type": "cp"}]
        cases.append((cfg, ".token is required and must be a string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["plugins"] = [{"type": "cp", "token": "mod:Cls"}]
        cases.append((cfg, ".token must be a token"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["plugins"] = [{"type": 123, "token": "t"}]
        cases.append((cfg, ".type must be a string"))

        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["extensions"] = {}
        cases.append((cfg, "modules.extensions must be an array"))

        for candidate, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RuntimeError, re.escape(message)):
                    di._validate_core_module_schema(candidate)

    def test_core_schema_handles_none_plugin_and_extension_lists(self) -> None:
        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["plugins"] = None
        cfg["mugen"]["modules"]["extensions"] = None
        di._validate_core_module_schema(cfg)

    def test_core_schema_accepts_optional_gateway_tokens_and_extensions(self) -> None:
        cfg = _valid_core_config()
        cfg["mugen"]["modules"]["core"]["gateway"]["email"] = "smtp"
        cfg["mugen"]["modules"]["core"]["gateway"]["knowledge"] = "qdrant"
        cfg["mugen"]["modules"]["extensions"] = [
            {
                "type": "cp",
                "token": "core.cp.clear_history",
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
            def __init__(self, config, logging_gateway, relational_runtime):  # noqa: ANN001
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

    def test_build_provider_raises_relational_runtime_bootstrap_failure_strict(self) -> None:
        config = _valid_core_config()
        injector = di.injector.DependencyInjector(
            config=SimpleNamespace(),
            logging_gateway=Mock(),
        )

        class _DummyKeyval:  # pylint: disable=too-few-public-methods
            def __init__(self, config, logging_gateway, relational_runtime):  # noqa: ANN001
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

        self.assertIn("Provider bootstrap failed (keyval_storage_gateway)", str(raised.exception))
