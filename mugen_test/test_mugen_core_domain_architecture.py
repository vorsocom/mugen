"""Architecture tests for core domain boundary rules."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


class TestCoreDomainArchitecture(unittest.TestCase):
    """Ensures core domain modules remain infrastructure-agnostic."""

    def test_domain_modules_do_not_import_infrastructure_layers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        domain_root = repo_root / "mugen" / "core" / "domain"
        python_files = sorted(domain_root.rglob("*.py"))

        forbidden_prefixes = (
            "mugen.core.client",
            "mugen.core.gateway",
            "mugen.core.plugin",
            "mugen.core.service",
            "mugen.core.di",
            "quart",
            "sqlalchemy",
        )

        violations: list[str] = []

        for file_path in python_files:
            module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(module_tree):
                module_name = None
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module_name = alias.name
                        if module_name.startswith(forbidden_prefixes):
                            violations.append(f"{file_path}: import {module_name}")
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if module_name.startswith(forbidden_prefixes):
                        violations.append(f"{file_path}: from {module_name}")

        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
