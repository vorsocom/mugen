"""Test schema selection and legacy SQL rewriting for core migrations."""

import unittest
from unittest.mock import patch

from migrations.schema_contract import (
    resolve_core_schema,
    resolve_runtime_schema,
    rewrite_mugen_schema_sql,
)


class TestMigrationSchemaContract(unittest.TestCase):
    """Require explicit valid schemas before migrations construct qualified SQL."""

    def test_runtime_schema_requires_its_own_nonempty_environment_value(self) -> None:
        for environment in (
            {},
            {"MUGEN_ALEMBIC_SCHEMA": ""},
            {"MUGEN_ALEMBIC_SCHEMA": " \t\n "},
            {"MUGEN_ALEMBIC_CORE_SCHEMA": "core_schema"},
        ):
            with self.subTest(environment=environment):
                with patch.dict("os.environ", environment, clear=True):
                    with self.assertRaisesRegex(
                        RuntimeError, "Missing required migration schema"
                    ):
                        resolve_runtime_schema()

    def test_runtime_schema_trims_valid_identifiers_and_rejects_sql_syntax(
        self,
    ) -> None:
        for configured, expected in (
            (" tenant_core_42 ", "tenant_core_42"),
            ("_Core", "_Core"),
        ):
            with self.subTest(configured=configured):
                with patch.dict("os.environ", {"MUGEN_ALEMBIC_SCHEMA": configured}):
                    self.assertEqual(resolve_runtime_schema(), expected)
        for configured in (
            "9core",
            "core.schema",
            "core-schema",
            '"core"',
            "core; DROP SCHEMA x",
        ):
            with self.subTest(configured=configured):
                with patch.dict("os.environ", {"MUGEN_ALEMBIC_SCHEMA": configured}):
                    with self.assertRaisesRegex(
                        RuntimeError, "Invalid migration schema"
                    ):
                        resolve_runtime_schema()

    def test_core_environment_takes_precedence_over_default(self) -> None:
        with patch.dict("os.environ", {"MUGEN_ALEMBIC_CORE_SCHEMA": " core_live "}):
            self.assertEqual(resolve_core_schema(default="fallback"), "core_live")
            self.assertEqual(
                resolve_core_schema(default="invalid.default"), "core_live"
            )
            self.assertEqual(resolve_core_schema(), "core_live")
        with patch.dict("os.environ", {"MUGEN_ALEMBIC_CORE_SCHEMA": "invalid.core"}):
            with self.assertRaisesRegex(RuntimeError, "Invalid migration schema"):
                resolve_core_schema(default="valid_default")

    def test_core_default_only_applies_to_missing_or_blank_environment(self) -> None:
        for environment in (
            {},
            {"MUGEN_ALEMBIC_CORE_SCHEMA": ""},
            {"MUGEN_ALEMBIC_CORE_SCHEMA": " \t "},
        ):
            with self.subTest(environment=environment):
                with patch.dict("os.environ", environment, clear=True):
                    self.assertEqual(
                        resolve_core_schema(default=" _core_42 "), "_core_42"
                    )
                    for default in (None, "", "  ", 42):
                        with self.subTest(default=default):
                            with self.assertRaisesRegex(
                                RuntimeError, "Missing required migration schema"
                            ):
                                resolve_core_schema(default=default)
                    with self.assertRaisesRegex(
                        RuntimeError, "Invalid migration schema"
                    ):
                        resolve_core_schema(default="invalid-default")

    def test_legacy_sql_qualifiers_follow_the_selected_runtime_schema(self) -> None:
        statement = (
            "ALTER TABLE mugen.child ADD CONSTRAINT parent_fk "
            "FOREIGN KEY (parent_id) REFERENCES mugen.parent(id); "
            "SELECT * FROM mugen_archive.parent JOIN public.reference USING (id);"
        )
        expected = (
            "ALTER TABLE tenant_core.child ADD CONSTRAINT parent_fk "
            "FOREIGN KEY (parent_id) REFERENCES tenant_core.parent(id); "
            "SELECT * FROM mugen_archive.parent JOIN public.reference USING (id);"
        )
        self.assertEqual(
            rewrite_mugen_schema_sql(statement, schema="tenant_core"), expected
        )
        self.assertEqual(rewrite_mugen_schema_sql(statement, schema="mugen"), statement)
        self.assertEqual(rewrite_mugen_schema_sql("", schema="tenant_core"), "")
        self.assertEqual(
            rewrite_mugen_schema_sql("SELECT 1", schema="tenant_core"), "SELECT 1"
        )

    def test_legacy_sql_rejects_non_string_statements(self) -> None:
        for statement in (None, b"SELECT 1", 7, ["SELECT 1"]):
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(
                    RuntimeError, "Migration SQL statement must be a string"
                ):
                    rewrite_mugen_schema_sql(statement, schema="tenant_core")
