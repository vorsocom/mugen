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
