"""Unit tests for core utility config/security helpers."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from mugen.core.utility.rdbms_schema import (
    qualify_sql_name,
    resolve_core_rdbms_schema,
    validate_sql_identifier,
)
from mugen.core.utility.security import (
    validate_matrix_secret_encryption_key,
    validate_quart_secret_key,
)


class TestMugenUtilityRdbmsSchema(unittest.TestCase):
    """Covers core schema contract helpers."""

    def test_validate_sql_identifier_accepts_valid_values(self) -> None:
        self.assertEqual(
            validate_sql_identifier("core_runtime", label="schema"),
            "core_runtime",
        )

    def test_validate_sql_identifier_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "expected SQL identifier string"):
            validate_sql_identifier(123, label="schema")
        with self.assertRaisesRegex(RuntimeError, "Invalid schema"):
            validate_sql_identifier("bad-schema", label="schema")

    def test_resolve_core_rdbms_schema_requires_explicit_value(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema({})
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema(
                {"rdbms": {"migration_tracks": {"core": {"schema": ""}}}}
            )

    def test_resolve_core_rdbms_schema_resolves_dict_value(self) -> None:
        self.assertEqual(
            resolve_core_rdbms_schema(
                {"rdbms": {"migration_tracks": {"core": {"schema": "core_runtime"}}}}
            ),
            "core_runtime",
        )

    def test_resolve_core_rdbms_schema_resolves_namespace_and_rejects_invalid(self) -> None:
        config = SimpleNamespace(
            rdbms=SimpleNamespace(
                migration_tracks=SimpleNamespace(
                    core=SimpleNamespace(schema="core_runtime"),
                )
            )
        )
        self.assertEqual(resolve_core_rdbms_schema(config), "core_runtime")
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema(SimpleNamespace(rdbms=None))
        with self.assertRaisesRegex(
            RuntimeError,
            "rdbms.migration_tracks.core.schema is required",
        ):
            resolve_core_rdbms_schema(
                SimpleNamespace(rdbms=SimpleNamespace())
            )

        with self.assertRaisesRegex(RuntimeError, "Invalid rdbms.migration_tracks.core.schema"):
            resolve_core_rdbms_schema(
                {"rdbms": {"migration_tracks": {"core": {"schema": "bad-schema"}}}}
            )

    def test_qualify_sql_name_validates_parts(self) -> None:
        self.assertEqual(
            qualify_sql_name(schema="core_runtime", name="core_keyval_entry"),
            "core_runtime.core_keyval_entry",
        )
        with self.assertRaisesRegex(RuntimeError, "Invalid name"):
            qualify_sql_name(schema="core_runtime", name="bad-name")


class TestMugenUtilitySecurity(unittest.TestCase):
    """Covers Quart secret-key validation helper."""

    def test_validate_quart_secret_key_accepts_strong_value(self) -> None:
        secret = "0123456789abcdef0123456789abcdef"
        self.assertEqual(validate_quart_secret_key(secret), secret)

    def test_validate_quart_secret_key_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be a string"):
            validate_quart_secret_key(123)
        with self.assertRaisesRegex(RuntimeError, "must be non-empty"):
            validate_quart_secret_key("   ")
        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            validate_quart_secret_key("short")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_quart_secret_key("changemechangemechangemechangeme")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_quart_secret_key("<set-quart-secret-key-xxxxxxxxxxxxx>")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_quart_secret_key("<aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa>")

    def test_validate_matrix_secret_encryption_key_accepts_strong_value(self) -> None:
        secret = "0123456789abcdef0123456789abcdef"
        self.assertEqual(validate_matrix_secret_encryption_key(secret), secret)

    def test_validate_matrix_secret_encryption_key_rejects_invalid_values(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be a string"):
            validate_matrix_secret_encryption_key(123)
        with self.assertRaisesRegex(RuntimeError, "must be non-empty"):
            validate_matrix_secret_encryption_key("   ")
        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            validate_matrix_secret_encryption_key("short")
        with self.assertRaisesRegex(RuntimeError, "must not use placeholder"):
            validate_matrix_secret_encryption_key("<set-secret-encryption-key>")
