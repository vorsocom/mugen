"""Architecture guards for the new agent-runtime layer."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


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
                    if alias.name.startswith(forbidden_prefixes):
                        violations.append(f"{file_path}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if module_name.startswith(forbidden_prefixes):
                    violations.append(f"{file_path}: from {module_name}")
    return violations


class TestMugenAgentRuntimeArchitecture(unittest.TestCase):
    """Keep agent contracts and core orchestration cleanly separated."""

    def test_agent_contracts_do_not_import_plugin_or_impl_layers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        contract_root = repo_root / "mugen" / "core" / "contract" / "agent"
        violations = _find_import_violations(
            python_files=sorted(contract_root.rglob("*.py")),
            forbidden_prefixes=(
                "mugen.core.api",
                "mugen.core.bootstrap",
                "mugen.core.client",
                "mugen.core.di",
                "mugen.core.gateway.",
                "mugen.core.plugin",
                "mugen.core.runtime",
                "mugen.core.service",
            ),
        )
        self.assertEqual(violations, [])

    def test_core_agent_runtime_service_avoids_plugin_models_and_adapter_impls(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        service_file = repo_root / "mugen" / "core" / "service" / "agent_runtime.py"
        violations = _find_import_violations(
            python_files=[service_file],
            forbidden_prefixes=(
                "mugen.core.client",
                "mugen.core.gateway.",
                "mugen.core.plugin",
                "mugen.core.runtime.",
            ),
        )
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
