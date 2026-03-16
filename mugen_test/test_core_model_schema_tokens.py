"""Guard tests that keep model schema references tokenized."""

from __future__ import annotations

from pathlib import Path
import unittest


class TestCoreModelSchemaTokens(unittest.TestCase):
    """Ensures model code does not hard-code concrete core schema names."""

    def test_model_files_reject_hardcoded_mugen_schema_literals(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        model_files = sorted((repo_root / "mugen" / "core" / "plugin").glob("**/model/**/*.py"))
        model_files.extend(
            sorted((repo_root / "mugen" / "core" / "plugin").glob("**/model/*.py"))
        )

        failures: list[str] = []
        for path in model_files:
            source = path.read_text(encoding="utf-8")
            if '{"schema": "mugen"}' in source:
                failures.append(f"{path}: hardcoded schema dict literal")
            if 'schema="mugen"' in source:
                failures.append(f"{path}: hardcoded schema keyword literal")
            if '"mugen.' in source:
                failures.append(f"{path}: hardcoded schema-qualified literal")

        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
