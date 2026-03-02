"""Regression tests for strict ILoggingGateway call-site usage."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


class TestLoggingGatewayContractRegression(unittest.TestCase):
    """Prevent stdlib-style variadic logging calls on gateway paths."""

    def test_gateway_calls_use_single_message_argument(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        scan_paths = [
            repo_root / "mugen" / "core",
            repo_root / "mugen" / "__init__.py",
        ]
        level_methods = {"critical", "debug", "error", "info", "warning"}

        violations: list[str] = []
        for scan_path in scan_paths:
            python_files = [scan_path] if scan_path.is_file() else sorted(
                scan_path.rglob("*.py")
            )
            for file_path in python_files:
                module_tree = ast.parse(file_path.read_text(encoding="utf-8"))
                module_uses_logging_gateway_type = _imports_ilogging_gateway(module_tree)
                for node in ast.walk(module_tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not isinstance(node.func, ast.Attribute):
                        continue
                    if node.func.attr not in level_methods:
                        continue
                    if len(node.args) <= 1:
                        continue
                    receiver = _receiver_path(node.func.value)
                    if not _looks_like_logging_gateway_receiver(
                        receiver,
                        module_uses_logging_gateway_type=module_uses_logging_gateway_type,
                    ):
                        continue
                    violations.append(
                        f"{file_path}:{node.lineno}: {receiver}.{node.func.attr}() "
                        "uses variadic arguments"
                    )

        self.assertEqual(violations, [])


def _imports_ilogging_gateway(module_tree: ast.Module) -> bool:
    for node in module_tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module != "mugen.core.contract.gateway.logging":
            continue
        for alias in node.names:
            if alias.name == "ILoggingGateway":
                return True
    return False


def _receiver_path(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _receiver_path(node.value)
        return f"{base}.{node.attr}"
    return "<unknown>"


def _looks_like_logging_gateway_receiver(
    receiver: str,
    *,
    module_uses_logging_gateway_type: bool,
) -> bool:
    if "logging_gateway" in receiver:
        return True
    if module_uses_logging_gateway_type and receiver in {"logger", "self._logger"}:
        return True
    return False


if __name__ == "__main__":
    unittest.main()
