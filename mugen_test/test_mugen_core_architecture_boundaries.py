"""Architecture boundary guards for core clean-architecture layering."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


class TestCoreArchitectureBoundaries(unittest.TestCase):
    """Fail fast when clean-architecture boundaries are crossed."""

    def test_domain_use_case_layer_stays_infrastructure_free(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        domain_use_case_root = repo_root / "mugen" / "core" / "domain" / "use_case"
        forbidden_prefixes = (
            "quart",
            "mugen.core.api",
            "mugen.core.bootstrap",
            "mugen.core.client",
            "mugen.core.di",
            "mugen.core.gateway",
            "mugen.core.runtime",
            "mugen.core.service",
        )
        violations = _find_import_violations(
            python_files=sorted(domain_use_case_root.rglob("*.py")),
            forbidden_prefixes=forbidden_prefixes,
        )
        self.assertEqual(violations, [])

    def test_contract_layer_does_not_import_implementation_layers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        contract_root = repo_root / "mugen" / "core" / "contract"
        forbidden_prefixes = (
            "mugen.core.api",
            "mugen.core.bootstrap",
            "mugen.core.client",
            "mugen.core.di",
            "mugen.core.gateway",
            "mugen.core.plugin",
            "mugen.core.runtime",
            "mugen.core.service",
        )
        violations = _find_import_violations(
            python_files=sorted(contract_root.rglob("*.py")),
            forbidden_prefixes=forbidden_prefixes,
        )
        self.assertEqual(violations, [])

    def test_adapter_layers_do_not_import_api_or_runtime_layers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        adapter_roots = [
            repo_root / "mugen" / "core" / "client",
            repo_root / "mugen" / "core" / "gateway",
        ]
        violations: list[str] = []
        for adapter_root in adapter_roots:
            violations += _find_import_violations(
                python_files=sorted(adapter_root.rglob("*.py")),
                forbidden_prefixes=(
                    "mugen.core.api",
                    "mugen.core.runtime",
                ),
            )
        self.assertEqual(violations, [])

    def test_service_layer_does_not_import_plugin_or_adapter_implementations(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        service_root = repo_root / "mugen" / "core" / "service"
        forbidden_prefixes = (
            "mugen.core.api",
            "mugen.core.bootstrap",
            "mugen.core.client",
            "mugen.core.gateway.",
            "mugen.core.plugin",
            "mugen.core.runtime.",
        )
        violations = _find_import_violations(
            python_files=sorted(service_root.rglob("*.py")),
            forbidden_prefixes=forbidden_prefixes,
        )
        self.assertEqual(violations, [])

    def test_runtime_layer_does_not_import_di_or_implementation_layers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        runtime_root = repo_root / "mugen" / "core" / "runtime"
        forbidden_prefixes = (
            "mugen.core.di",
            "mugen.core.gateway.",
            "mugen.core.plugin",
            "mugen.core.service.",
        )
        violations = _find_import_violations(
            python_files=sorted(runtime_root.rglob("*.py")),
            forbidden_prefixes=forbidden_prefixes,
        )
        self.assertEqual(violations, [])

    def test_bootstrap_orchestration_avoids_direct_adapter_imports(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        orchestration_files = [
            repo_root / "mugen" / "__init__.py",
            repo_root / "quartman.py",
        ]
        forbidden_prefixes = (
            "mugen.core.client.",
            "mugen.core.gateway.",
            "mugen.core.service.",
        )
        violations = _find_import_violations(
            python_files=orchestration_files,
            forbidden_prefixes=forbidden_prefixes,
        )
        self.assertEqual(violations, [])

    def test_api_endpoint_does_not_depend_on_runtime_parsing_helpers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        endpoint_file = repo_root / "mugen" / "core" / "api" / "endpoint.py"
        violations = _find_import_violations(
            python_files=[endpoint_file],
            forbidden_prefixes=(
                "mugen.core.runtime.phase_b_controls",
            ),
        )
        self.assertEqual(violations, [])

    def test_migration_env_uses_contract_helpers_for_core_extension_config(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        env_source = (repo_root / "migrations" / "env.py").read_text(encoding="utf-8")
        self.assertIn(
            "from mugen.core.contract.migration_config import",
            env_source,
        )
        self.assertNotIn('core_cfg.get("plugins"', env_source)

    def test_di_schema_validation_uses_contract_matrix_runtime_validator(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        di_source = (repo_root / "mugen" / "core" / "di" / "__init__.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "from mugen.core.contract.matrix_runtime_config import",
            di_source,
        )
        self.assertIn(
            "validate_matrix_enabled_runtime_config(config)",
            di_source,
        )
        self.assertIn(
            "from mugen.core.contract.telegram_runtime_config import",
            di_source,
        )
        self.assertIn(
            "validate_telegram_enabled_runtime_config(config)",
            di_source,
        )

    def test_runtime_bootstrap_parser_is_contract_owned(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        contract_parser = (
            repo_root / "mugen" / "core" / "contract" / "runtime_bootstrap.py"
        )
        legacy_runtime_parser = (
            repo_root / "mugen" / "core" / "runtime" / "bootstrap_contract.py"
        )
        self.assertTrue(contract_parser.is_file())
        self.assertFalse(legacy_runtime_parser.exists())

    def test_di_and_runtime_depend_on_contract_runtime_bootstrap_parser(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        for module_path in (
            repo_root / "mugen" / "core" / "di" / "__init__.py",
            repo_root / "mugen" / "core" / "runtime" / "phase_b_controls.py",
            repo_root / "mugen" / "__init__.py",
            repo_root / "quartman.py",
        ):
            source = module_path.read_text(encoding="utf-8")
            self.assertIn(
                "from mugen.core.contract.runtime_bootstrap import",
                source,
            )
            self.assertNotIn(
                "mugen.core.runtime.bootstrap_contract",
                source,
            )

    def test_matrix_runtime_contract_module_stays_infrastructure_free(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        contract_module = (
            repo_root / "mugen" / "core" / "contract" / "matrix_runtime_config.py"
        )
        violations = _find_import_violations(
            python_files=[contract_module],
            forbidden_prefixes=(
                "quart",
                "mugen.core.api",
                "mugen.core.bootstrap",
                "mugen.core.client",
                "mugen.core.di",
                "mugen.core.gateway",
                "mugen.core.plugin",
                "mugen.core.runtime",
                "mugen.core.service",
                "sqlalchemy",
                "nio",
            ),
        )
        self.assertEqual(violations, [])

    def test_telegram_runtime_contract_module_stays_infrastructure_free(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        contract_module = (
            repo_root / "mugen" / "core" / "contract" / "telegram_runtime_config.py"
        )
        violations = _find_import_violations(
            python_files=[contract_module],
            forbidden_prefixes=(
                "quart",
                "mugen.core.api",
                "mugen.core.bootstrap",
                "mugen.core.client",
                "mugen.core.di",
                "mugen.core.gateway",
                "mugen.core.plugin",
                "mugen.core.runtime",
                "mugen.core.service",
                "sqlalchemy",
                "nio",
            ),
        )
        self.assertEqual(violations, [])

    def test_client_shutdown_timeout_resolution_uses_contract_parser(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        for client_module_path in (
            repo_root / "mugen" / "core" / "client" / "matrix.py",
            repo_root / "mugen" / "core" / "client" / "telegram.py",
            repo_root / "mugen" / "core" / "client" / "whatsapp.py",
        ):
            source = client_module_path.read_text(encoding="utf-8")
            self.assertIn(
                "from mugen.core.contract.runtime_bootstrap import parse_runtime_bootstrap_settings",
                source,
            )
            self.assertNotIn("_default_shutdown_timeout_seconds", source)


def _find_import_violations(
    *,
    python_files: list[Path],
    forbidden_prefixes: tuple[str, ...],
) -> list[str]:
    violations: list[str] = []
    for file_path in python_files:
        module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(module_tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name
                    if module_name.startswith(forbidden_prefixes):
                        violations.append(f"{file_path}: import {module_name}")
                continue
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name.startswith(forbidden_prefixes):
                    violations.append(f"{file_path}: from {module_name}")
    return violations


if __name__ == "__main__":
    unittest.main()
