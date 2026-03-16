"""Import-boundary tests for core package layering."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


class TestMugenCoreImportBoundaries(unittest.TestCase):
    """Prevent core package regressions that import plugin modules directly."""

    def test_core_outside_plugin_does_not_import_plugin_package(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        core_root = repo_root / "mugen" / "core"
        plugin_root = core_root / "plugin"
        violations: list[str] = []

        for source_path in core_root.rglob("*.py"):
            if plugin_root in source_path.parents:
                continue
            tree = ast.parse(source_path.read_text(encoding="utf8"), filename=str(source_path))
            rel_path = source_path.relative_to(repo_root)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.startswith("mugen.core.plugin"):
                            violations.append(
                                f"{rel_path}:{node.lineno} imports {alias.name}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    module_name = node.module or ""
                    if node.level == 0:
                        if module_name.startswith("mugen.core.plugin"):
                            violations.append(
                                f"{rel_path}:{node.lineno} imports from {module_name}"
                            )
                        continue
                    if module_name == "plugin" or module_name.startswith("plugin."):
                        violations.append(
                            f"{rel_path}:{node.lineno} uses relative import from {module_name}"
                        )

        self.assertEqual(
            violations,
            [],
            msg=(
                "Core import boundary violation(s) detected.\n"
                + "\n".join(violations)
            ),
        )
