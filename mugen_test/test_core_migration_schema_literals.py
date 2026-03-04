"""Guard tests that keep core migration schema literals contract-safe."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


class TestCoreMigrationSchemaLiterals(unittest.TestCase):
    """Ensures core revisions do not bypass runtime schema rewrite contract."""

    def test_revisions_reject_hardcoded_schema_literals_outside_rewrite_wrappers(
        self,
    ) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        revisions = sorted((repo_root / "migrations" / "versions").glob("*.py"))
        failures: list[str] = []

        allowed_wrapper_calls = {
            "_sql",
            "_sql_text",
            "_execute",
            "rewrite_mugen_schema_sql",
        }

        for revision_path in revisions:
            source = revision_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            parents: dict[ast.AST, ast.AST] = {}
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    parents[child] = node

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "schema":
                        continue
                    if (
                        isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                        and keyword.value.value.strip() == "mugen"
                    ):
                        failures.append(
                            f"{revision_path}:{keyword.value.lineno}: hardcoded schema='mugen'"
                        )

            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                value = node.value
                if "mugen." not in value:
                    continue

                if "com.vorsocomputing.mugen." in value:
                    continue
                if "mugen.core." in value:
                    continue
                if "mugen.modules" in value:
                    continue

                allowed = False
                parent = parents.get(node)
                while parent is not None:
                    if isinstance(parent, ast.Call):
                        call_name = None
                        if isinstance(parent.func, ast.Name):
                            call_name = parent.func.id
                        elif isinstance(parent.func, ast.Attribute):
                            call_name = parent.func.attr
                        if call_name in allowed_wrapper_calls:
                            allowed = True
                            break
                    parent = parents.get(parent)

                if allowed:
                    continue
                failures.append(
                    f"{revision_path}:{node.lineno}: hardcoded schema literal contains 'mugen.'"
                )

        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
